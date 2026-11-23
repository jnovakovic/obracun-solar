"""
Obračun električne energije za kućanstvo sa sunčanom elektranom.

Two settlement schemes are modelled (ZOIEVUK, NN 138/21, 83/23, 78/25, čl. 51):

  'month'  Mjesečno netiranje (čl. 51. st. 21.): per tariff, energy, network charges, levies
           and VAT are billed on the monthly difference between imported and exported energy.
           A monthly surplus in a tariff is bought at 0.8 * Cp (Cp = energy price of the tariff).

  '15min'  Neto obračun (čl. 51. st. 7., st. 5.): all imported energy is billed in full,
           exported energy is credited at  Ci = k * PKC * min(1, Ep/Ei)
           k = kSO for households (1 until/as set by HERA; 0.9 for institutions),
           k = 0.9 for 'krajnji kupac s vlastitom proizvodnjom' (business).
           Import and export are determined per interval of the input data (15 min or 1 h).

Input convention (kept from the original code so other scripts keep working):
  production_data['ac_power_kw']  PV energy per interval in kWh   (despite the column name)
  consumption_df['consumption_kw'] load energy per interval in kWh (despite the column name)
  Both on the same DatetimeIndex in local standard time (CET, UTC+1, no DST switch).

Comparison switches (defaults = corrected behaviour; app_v2.py uses the original behaviour):
  threshold_on_import, pkc_includes_subsidy, discount_first_year, escalate_all_prices, inflate_inverter.

High tariff (VT) 07-21 h, low tariff (NT) 21-07 h, winter time (HEP). Every interval is in exactly
one tariff, whatever the time stamp offset (HH:00, HH:10, HH:15 ...).
"""
import numpy as np
import pandas as pd

MJESECI = ['Siječanj', 'Veljača', 'Ožujak', 'Travanj', 'Svibanj', 'Lipanj',
           'Srpanj', 'Kolovoz', 'Rujan', 'Listopad', 'Studeni', 'Prosinac']

VT_START, VT_END = 7, 21                 # VT from 07:00 to 21:00 (CET)
WINTER_MONTHS = (1, 2, 3, 10, 11, 12)    # six-month blocks for the 3,000 kWh price threshold
SURPLUS_FACTOR_NM = 0.8                  # Ci = 0.8 * Cp under monthly netting (čl. 51. st. 21.)
FACTOR_BUSINESS = 0.9                    # Ci = 0.9 * PKC ... (čl. 51. st. 5.)
# PKC = average unit energy price actually paid, i.e. including the part above the 3,000 kWh threshold.
# Set to False to reproduce the original app (energy price weighted by VT/NT imports only).
PKC_INCLUDES_SUBSIDY_LIMIT = True
PRICE_COLS_NOT_ESCALATED = ('VAT', 'Sub_increase')

_COLS = ['Opis', 'Iznos EUR', 'Stanje od', 'Stanje do', 'Potrošak', 'Količina', 'Jedinica mjere', 'Cijena EUR/kWh']


# --------------------------------------------------------------------------- energy balance
def vt_mask(index, start=VT_START, end=VT_END):
    """True for intervals in the high tariff. Uses the hour only, so every interval is VT or NT."""
    h = np.asarray(index.hour)
    return (h >= start) & (h < end)


def month_tariff_keys(index, mask=None):
    """Integer key 0..23 = 2*(month-1) + (0 VT | 1 NT) for every interval."""
    if mask is None:
        mask = vt_mask(index)
    return (np.asarray(index.month) - 1) * 2 + np.where(mask, 0, 1)


def monthly_balance(load_kwh, pv_kwh, keys):
    """Monthly totals per tariff, arrays of shape (12, 2) [:,0]=VT, [:,1]=NT.
    'from' = energy taken from the grid (>=0), 'to' = energy delivered to the grid (<=0)."""
    load = np.asarray(load_kwh, dtype=float)
    pv = np.broadcast_to(np.asarray(pv_kwh, dtype=float), load.shape)
    net = load - pv

    def agg(x):
        return np.bincount(keys, weights=x, minlength=24).reshape(12, 2)

    return {'Load': agg(load), 'PV': agg(pv),
            'from': agg(np.clip(net, 0, None)), 'to': agg(np.clip(net, None, 0))}


def _energy_arrays(bal, sub_kWh, net_interval, threshold_on_import=True):
    """Monthly energy table as a dict of arrays (length 12), incl. the 3,000 kWh threshold split."""
    L, P = np.round(bal['Load'], 2), np.round(bal['PV'], 2)
    F, T = np.round(bal['from'], 2), np.round(bal['to'], 2)
    net = F + T
    E = {}
    for j, t in enumerate(('HT', 'LT')):
        E[f'Load_{t}_kWh'], E[f'PV_{t}_kWh'], E[f'net_{t}_kWh'] = L[:, j], P[:, j], net[:, j]
        E[f'from_Grid_{t}_kWh'], E[f'to_Grid_{t}_kWh'] = F[:, j], T[:, j]
        cf, ct = np.cumsum(bal['from'][:, j]), np.cumsum(bal['to'][:, j])
        E[f'{t} Stanje do'], E[f'{t} Stanje od'] = np.round(cf, 2), np.round(np.r_[0, cf[:-1]], 2)
        E[f'predano_{t} Stanje do'], E[f'predano_{t} Stanje od'] = np.round(ct, 2), np.round(np.r_[0, ct[:-1]], 2)
    E['Load_total_kWh'], E['PV_total_kWh'], E['net_total_kWh'] = L.sum(1), P.sum(1), net.sum(1)

    # energy counted against the threshold: netted kWh (net metering) or all imported kWh (net billing).
    # threshold_on_import=False reproduces the original app (netted kWh in both schemes).
    billed = F if (net_interval == '15min' and threshold_on_import) else np.clip(net, 0, None)
    tot = billed.sum(1)
    cum, prev_over = np.zeros(12), np.zeros(12)
    for months in (WINTER_MONTHS, tuple(m for m in range(1, 13) if m not in WINTER_MONTHS)):
        i = np.array(months) - 1
        c = np.cumsum(tot[i]); over = np.clip(c - sub_kWh, 0, None)
        cum[i], prev_over[i] = c, np.r_[0, over[:-1]]
    over = np.clip(cum - sub_kWh, 0, None)
    van = over - prev_over                                   # kWh above the threshold in this month
    ht_van = np.where(tot > 0, np.round(van * billed[:, 0] / np.where(tot > 0, tot, 1)), 0.0)
    E['Preostalo_subv_kWh'] = sub_kWh - cum
    E['HT_van_subv'], E['LT_van_subv'] = ht_van, van - ht_van
    return E


_ENERGY_ORDER = ['Load_total_kWh', 'PV_total_kWh', 'net_total_kWh', 'Load_HT_kWh', 'PV_HT_kWh', 'net_HT_kWh',
                 'Load_LT_kWh', 'PV_LT_kWh', 'net_LT_kWh', 'to_Grid_HT_kWh', 'to_Grid_LT_kWh',
                 'from_Grid_HT_kWh', 'from_Grid_LT_kWh', 'Preostalo_subv_kWh',
                 'HT Stanje od', 'HT Stanje do', 'LT Stanje od', 'LT Stanje do',
                 'predano_HT Stanje od', 'predano_HT Stanje do', 'predano_LT Stanje od', 'predano_LT Stanje do',
                 'HT_van_subv', 'LT_van_subv']


def energy_calculation(production_data, consumption_df, sub_kWh=3000, net_interval='month', mask=None, threshold_on_import=True):
    """Monthly energy table (index 1..12) with the same columns as the original app."""
    keys = month_tariff_keys(consumption_df.index, mask)
    bal = monthly_balance(consumption_df['consumption_kw'].to_numpy(), production_data['ac_power_kw'].to_numpy(), keys)
    E = _energy_arrays(bal, sub_kWh, net_interval, threshold_on_import)
    return pd.DataFrame({c: E[c] for c in _ENERGY_ORDER}, index=range(1, 13))


# --------------------------------------------------------------------------- invoice
def _prices(prices_df):
    return {k: float(v) for k, v in prices_df.iloc[0].items()}


def _invoice_arrays(E, p, sub_kWh, net_interval, kSO, pkc_includes_subsidy=None):
    """All invoice lines for 12 months at once. Keys are the row numbers of the original bill layout."""
    R, R2 = np.round, (lambda x: np.round(x, 2))
    FH, FL, TH, TL = E['from_Grid_HT_kWh'], E['from_Grid_LT_kWh'], E['to_Grid_HT_kWh'], E['to_Grid_LT_kWh']
    potFH, potFL, potTH, potTL = R(FH), R(FL), -R(TH), -R(TL)        # meter readings, whole kWh, >=0
    netH, netL = potFH - potTH, potFL - potTL
    if net_interval == 'month':
        qH, qL = np.maximum(netH, 0), np.maximum(netL, 0)
    else:
        qH, qL = potFH, potFL
    vanH, vanL = R(E['HT_van_subv']), R(E['LT_van_subv'])
    pH_van, pL_van = round(p['Energy_HT'] * (1 + p['Sub_increase']), 6), round(p['Energy_LT'] * (1 + p['Sub_increase']), 6)
    one = np.ones(12)

    a = {}
    q = {16: qH, 17: qL, 18: one, 20: qH, 21: qL, 23: qH - vanH, 24: qL - vanL, 25: vanH, 26: vanL, 27: one}
    pr = {16: p['Distr_HT'] * one, 17: p['Distr_LT'] * one, 18: p['Grid_fee'] * one, 20: p['Trans_HT'] * one,
          21: p['Trans_LT'] * one, 23: p['Energy_HT'] * one, 24: p['Energy_LT'] * one, 25: pH_van * one,
          26: pL_van * one, 27: p['Prod_fee'] * one}
    for k in q:
        a[k] = R2(q[k] * pr[k])
    a[19] = R2(a[16] + a[17] + a[18])
    a[22] = R2(a[20] + a[21])
    a[28] = R2(a[23] + a[24] + a[25] + a[26] + a[27])
    a[29] = R2(a[19] + a[22] + a[28])
    q[30] = q[31] = qH + qL
    pr[30], pr[31] = p['RES'] * one, p['Solidarity'] * one
    a[30], a[31] = R2(q[30] * pr[30]), R2(q[31] * pr[31])
    a[1], a[2], a[3] = a[29], a[30], a[31]
    a[4] = -a[3]                                             # solidarity fee discount for households
    a[5] = R2(a[1] + a[2] + a[3] + a[4])
    a[6] = R2(a[5] * p['VAT'])
    a[7] = R2(a[5] + a[6])

    # value of energy delivered to the grid
    if net_interval == 'month':
        sH, sL = SURPLUS_FACTOR_NM * p['Energy_HT'] * one, SURPLUS_FACTOR_NM * p['Energy_LT'] * one
        a[8] = -(R2(np.minimum(netH, 0) * sH) + R2(np.minimum(netL, 0) * sL))
        q[32], q[33] = -R(np.minimum(netH, 0)), -R(np.minimum(netL, 0))
    else:
        Ep, Ei = potFH + potFL, potTH + potTL
        ratio = np.where(Ei > 0, Ep / np.where(Ei > 0, Ei, 1), 1.0)
        if PKC_INCLUDES_SUBSIDY_LIMIT if pkc_includes_subsidy is None else pkc_includes_subsidy:
            energy_cost = q[23] * p['Energy_HT'] + q[24] * p['Energy_LT'] + vanH * pH_van + vanL * pL_van
        else:
            energy_cost = potFH * p['Energy_HT'] + potFL * p['Energy_LT']
        pkc = energy_cost / np.maximum(1, Ep)
        sH = sL = kSO * np.minimum(1, ratio) * pkc
        a[8] = -(R2(TH * sH) + R2(TL * sL))
        q[32], q[33] = potTH, potTL
    pr[32], pr[33] = sH, sL
    a[32], a[33] = R2(q[32] * sH), R2(q[33] * sL)
    a[9] = a[7] - a[8]
    meter = {12: (E['HT Stanje od'], E['HT Stanje do'], potFH), 13: (E['LT Stanje od'], E['LT Stanje do'], potFL),
             14: (-E['predano_HT Stanje od'], -E['predano_HT Stanje do'], potTH),
             15: (-E['predano_LT Stanje od'], -E['predano_LT Stanje do'], potTL)}
    return a, q, pr, meter


def _row_text(sub_kWh, vat):
    return {1: ('Ukupan iznos za el. energiju (opskrba i korištenje mreže)', None),
            2: ('Naknada za poticanje proizvodnje iz obnovljivih izvora', None), 3: ('Solidarna naknada', None),
            4: ('Popust za solidarnu naknadu', None), 5: ('Porezna osnovica', None), 6: (f'PDV {vat * 100} %', None),
            7: ('UKUPAN IZNOS RAČUNA', None), 8: ('Vrijednost preuzete električne energije', None),
            9: ('Ukupno za platiti', None), 10: ('', None), 11: ('Početno i krajnje stanje očitanja brojila', None),
            12: ('RVT R1', None), 13: ('RNT R2', None), 14: ('RVT R1 PR', None), 15: ('RNT R2 PR', None),
            16: ('RVT Distribucija', 'kWh'), 17: ('RNT Distribucija', 'kWh'),
            18: ('Naknada za OMM Distribucija', 'Mjesec'), 19: ('Distribucija Ukupno', None),
            20: ('RVT Prijenos', 'kWh'), 21: ('RNT Prijenos', 'kWh'), 22: ('Prijenos Ukupno', None),
            23: ('RVT Opskrba', 'kWh'), 24: ('RNT Opskrba', 'kWh'), 25: (f'RVT Opskrba >{sub_kWh} kWh', 'kWh'),
            26: (f'RNT Opskrba >{sub_kWh} kWh', 'kWh'), 27: ('Naknada za opskrbu', 'Mjesec'),
            28: ('Opskrba Ukupno', None), 29: ('Ukupan iznos za el. energiju (opskrba i korištenje mreže)', None),
            30: ('Naknada za poticanje proizvodnje iz obnovljivih izvora', 'kWh'), 31: ('Solidarna naknada', 'kWh'),
            32: ('Neto višak energije VT', 'kWh'), 33: ('Neto višak energije NT', 'kWh')}


def _build_invoices(a, q, pr, meter, sub_kWh, vat):
    text = _row_text(sub_kWh, vat)
    rows = list(range(1, 34))
    racuni = {}
    for m, name in enumerate(MJESECI):
        d = {c: [np.nan] * 33 for c in _COLS}
        for r in rows:
            i = r - 1
            d['Opis'][i], unit = text[r]
            d['Jedinica mjere'][i] = unit if unit else np.nan
            if r in a:
                d['Iznos EUR'][i] = a[r][m]
            if r in q:
                d['Količina'][i] = q[r][m]
                d['Cijena EUR/kWh'][i] = pr[r][m]
            if r in meter:
                d['Stanje od'][i], d['Stanje do'][i], d['Potrošak'][i] = (x[m] for x in meter[r])
        racuni[name] = pd.DataFrame(d, index=rows)
    return racuni


def create_invoice(net_interval, obracun, prices_df, sub_kWh=3000, kSO=1.0, pkc_includes_subsidy=None):
    """Monthly bills (dict month name -> DataFrame) from the monthly energy table."""
    E = {c: obracun[c].to_numpy(dtype=float) for c in obracun.columns}
    p = _prices(prices_df)
    a, q, pr, meter = _invoice_arrays(E, p, sub_kWh, net_interval, kSO, pkc_includes_subsidy)
    return _build_invoices(a, q, pr, meter, sub_kWh, p['VAT'])


def year_total(obracun, racuni):
    """Monthly/annual energy balance with bills, and the annual bill as the sum of monthly bills."""
    cols = ['Load_HT_kWh', 'PV_HT_kWh', 'net_HT_kWh', 'from_Grid_HT_kWh', 'to_Grid_HT_kWh',
            'Load_LT_kWh', 'PV_LT_kWh', 'net_LT_kWh', 'from_Grid_LT_kWh', 'to_Grid_LT_kWh']
    b = obracun[cols].astype(float).round(2).copy()
    for c in ['Load', 'PV', 'net', 'from_Grid', 'to_Grid']:
        b[f'Total_{c}_kWh'] = obracun[f'{c}_HT_kWh'] + obracun[f'{c}_LT_kWh']
    b['Sub_kWh_left'] = obracun['Preostalo_subv_kWh']
    b['Bill'] = [racuni[m].loc[9, 'Iznos EUR'] for m in MJESECI]
    b.index = b.index.astype(object)
    b.loc['Year'] = b.sum().round(2)

    all_df = pd.concat([racuni[m] for m in MJESECI])
    g = all_df.groupby(level=0)[['Iznos EUR', 'Količina', 'Potrošak']].sum()
    g.insert(0, 'Opis', racuni['Siječanj']['Opis'])
    g['Stanje od'] = 0.0
    g['Stanje do'] = racuni['Prosinac']['Stanje do']
    g['Jedinica mjere'] = racuni['Siječanj']['Jedinica mjere']
    g['Cijena EUR/kWh'] = racuni['Siječanj']['Cijena EUR/kWh']
    for i in (32, 33):
        g.loc[i, 'Cijena EUR/kWh'] = g.loc[i, 'Iznos EUR'] / g.loc[i, 'Količina'] if g.loc[i, 'Količina'] else 0.0
    return b, g


def izvrši_obracun(production_data, consumption_df, prices_df, sub_kWh=3000, net_interval='month', kSO=1.0, mask=None,
                   threshold_on_import=True, pkc_includes_subsidy=None):
    """Full settlement for one year.
    net_interval: 'month' (mjesečno netiranje) or '15min' (neto obračun, per data interval).
    kSO: export price factor for net billing: 1.0 household (default), 0.9 institution or business.
    Returns (monthly energy table, monthly bills dict, monthly/annual balance, annual bill)."""
    obracun = energy_calculation(production_data, consumption_df, sub_kWh, net_interval, mask, threshold_on_import)
    racuni = create_invoice(net_interval, obracun, prices_df, sub_kWh, kSO, pkc_includes_subsidy)
    bilanca, godisnji = year_total(obracun, racuni)
    return obracun, racuni, bilanca, godisnji


# --------------------------------------------------------------------------- fast path for many runs
def annual_bill(bal, p, sub_kWh=3000, net_interval='month', kSO=1.0, threshold_on_import=True, pkc_includes_subsidy=None):
    """Annual bill (EUR) from a precomputed monthly balance and a price dict, without building tables."""
    E = _energy_arrays(bal, sub_kWh, net_interval, threshold_on_import)
    a, _, _, _ = _invoice_arrays(E, p, sub_kWh, net_interval, kSO, pkc_includes_subsidy)
    return float(a[9].sum())


def escalate_prices(p, factor, all_prices=True):
    """all_prices=False reproduces the original app: only columns with 'HT' or 'LT' in their name are escalated."""
    if all_prices:
        return {k: (v if k in PRICE_COLS_NOT_ESCALATED else v * factor) for k, v in p.items()}
    return {k: (v * factor if ('HT' in k.upper() or 'LT' in k.upper()) else v) for k, v in p.items()}


def loan_payment(principal, rate_pct, years):
    if principal <= 0 or years <= 0:
        return 0.0
    r = rate_pct / 100
    return principal / years if r == 0 else principal * r * (1 + r) ** years / ((1 + r) ** years - 1)


def _irr(flows):
    """IRR of a cash-flow series (t = 0, 1, ...). None if it does not exist in (-99 %, 100 %)."""
    flows = np.asarray(flows, float)
    t = np.arange(len(flows))
    f = lambda r: float(np.sum(flows / (1 + r) ** t))
    lo, hi = -0.99, 1.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(lo) * f(mid) > 0 else (lo, mid)
    return float((lo + hi) / 2)


def _payback(cum):
    """Discounted payback in years (fractional) from cumulative values at t = 0..N. None if not reached."""
    if cum[0] >= 0:
        return 0.0
    for y in range(1, len(cum)):
        if cum[y] >= 0:
            return float(y - 1 + (-cum[y - 1]) / (cum[y] - cum[y - 1]))
    return None


def analiza_isplativosti(pv_kwh, load_kwh, index, prices_df, capacity_kw, cost_per_kw=1000.0, incentive_pct=0.0,
                         loan_pct=0.0, loan_rate_pct=3.0, loan_years=10, discount_pct=4.0, inverter_cost=500.0,
                         inverter_year=10, lifetime=25, degradation_pct=0.8, om_pct=0.5, price_growth_pct=2.0,
                         inflation_pct=2.0, sub_kWh=3000, kSO=1.0, mask=None, discount_first_year=True,
                         escalate_all_prices=True, inflate_inverter=True, threshold_on_import=True, pkc_includes_subsidy=None):
    """Cash-flow analysis over the lifetime for monthly netting ('month') and net billing ('15min').
    Cash flows are nominal; year y is discounted with (1 + r)^y (or (1 + r)^(y-1) if discount_first_year=False);
    the investment (own funds) is at t = 0.
    Monthly netting is assumed for the whole lifetime."""
    keys = month_tariff_keys(index, mask)
    load = np.asarray(load_kwh, float); pv = np.asarray(pv_kwh, float)
    bal0 = monthly_balance(load, 0.0, keys)
    p0 = _prices(prices_df)

    total_cost = capacity_kw * cost_per_kw
    net_cost = total_cost * (1 - incentive_pct / 100)
    loan = net_cost * loan_pct / 100
    equity = net_cost - loan
    pay = loan_payment(loan, loan_rate_pct, loan_years)
    r = discount_pct / 100

    rows = []
    for y in range(1, lifetime + 1):
        p = escalate_prices(p0, (1 + price_growth_pct / 100) ** (y - 1), escalate_all_prices)
        bal = monthly_balance(load, pv * (1 - degradation_pct / 100) ** (y - 1), keys)
        row = {'Godina': y, 'Proizvodnja_kWh': float(bal['PV'].sum()),
               'Racun_bez_SE': annual_bill(bal0, p, sub_kWh, 'month'),
               'Racun_mjesecno': annual_bill(bal, p, sub_kWh, 'month'),
               'Racun_neto_obracun': annual_bill(bal, p, sub_kWh, '15min', kSO, threshold_on_import, pkc_includes_subsidy),
               'Odrzavanje': total_cost * om_pct / 100 * (1 + inflation_pct / 100) ** (y - 1),
               'Inverter': (inverter_cost * ((1 + inflation_pct / 100) ** (y - 1) if inflate_inverter else 1.0)
                            if y == inverter_year else 0.0),
               'Kredit': pay if y <= loan_years else 0.0}
        rows.append(row)
    df = pd.DataFrame(rows).set_index('Godina')
    disc = (1 + r) ** (df.index.to_numpy() - (0 if discount_first_year else 1))
    res = {}
    for key, col in (('month', 'Racun_mjesecno'), ('15min', 'Racun_neto_obracun')):
        cf = (df['Racun_bez_SE'] - df[col] - df['Odrzavanje'] - df['Inverter'] - df['Kredit']).to_numpy()
        dcf = cf / disc
        cum = np.r_[-equity, -equity + np.cumsum(dcf)]
        df[f'Novcani_tok_{key}'], df[f'Disk_tok_{key}'], df[f'Kumulativno_{key}'] = cf, dcf, cum[1:]
        res[key] = {'npv': float(cum[-1]), 'payback': _payback(cum), 'irr': _irr(np.r_[-equity, cf]),
                    'first_year_saving': float(df['Racun_bez_SE'].iloc[0] - df[col].iloc[0]),
                    'first_year_cash_flow': float(cf[0]), 'cumulative': cum}
    res['costs'] = {'total': total_cost, 'net': net_cost, 'equity': equity, 'loan': loan, 'loan_payment': pay}
    res['table'] = df
    return res


# --------------------------------------------------------------------------- legacy display helpers
def plot_bill_style_plotly(df):
    import plotly.graph_objects as go
    d = df[['Opis', 'Iznos EUR']].copy()
    opis = d['Opis'].tolist()
    iznos = [f"{x:,.2f}" if pd.notnull(x) else "" for x in d['Iznos EUR']]
    for i, o in enumerate(opis):
        if isinstance(o, str) and ('Ukupno' in o or 'UKUPAN' in o):
            opis[i], iznos[i] = f"<b>{o}</b>", f"<b>{iznos[i]}</b>"
    fig = go.Figure(data=[go.Table(
        columnwidth=[2, 1],
        header=dict(values=['Opis', 'Iznos EUR'], font=dict(size=12, family='Arial', color='white'),
                    fill_color='darkblue', align=['left', 'right'], line_color='darkslategray', height=30),
        cells=dict(values=[opis, iznos], font=dict(size=12, family='Arial', color='black'), fill_color='white',
                   align=['left', 'right'], line_color='lightgray', height=25))])
    fig.update_layout(autosize=True, margin=dict(l=0, r=0, t=5, b=0), height=30 + len(d) * 25,
                      showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig


def display_bill_table(fig, df_bill=None):
    import streamlit as st
    st.plotly_chart(fig, use_container_width=True)


def _mpl_table(df, widths, fmt, figsize_h):
    import matplotlib.pyplot as plt
    d = df.copy()
    for c, f in fmt.items():
        d[c] = d[c].apply(lambda x: f.format(x) if isinstance(x, (int, float, np.floating)) and pd.notnull(x) else ("" if pd.isnull(x) else x))
    fig, ax = plt.subplots(figsize=(12, max(0.3, figsize_h * len(d))))
    ax.axis('off')
    t = ax.table(cellText=d.values, colLabels=d.columns, cellLoc='left', loc='top', colWidths=widths, edges='open')
    t.auto_set_font_size(False); t.set_fontsize(12)
    for j in range(len(d.columns)):
        t[0, j].set_text_props(weight='bold'); t[0, j].visible_edges = 'B'
    fig.subplots_adjust(top=1, bottom=0, left=0, right=1)
    return fig


def plot_bill_style(df):
    return _mpl_table(df[['Opis', 'Iznos EUR']], [0.5, 0.25], {'Iznos EUR': '{:,.2f}'}, 0.03)


def plot_bill_style2(df):
    return _mpl_table(df[['Opis', 'Stanje od', 'Stanje do', 'Potrošak']], [0.3, 0.15, 0.15, 0.15],
                      {'Stanje od': '{:,.2f}', 'Stanje do': '{:,.2f}', 'Potrošak': '{:,.0f}'}, 0.08)


def plot_bill_style3(df):
    d = df[['Opis', 'Iznos EUR', 'Količina', 'Jedinica mjere', 'Cijena EUR/kWh']].rename(
        columns={'Cijena EUR/kWh': 'EUR/kWh', 'Jedinica mjere': 'Jedinica'})
    return _mpl_table(d, [0.5, 0.1, 0.1, 0.05, 0.1], {'Iznos EUR': '{:,.2f}', 'Količina': '{:,.0f}', 'EUR/kWh': '{:,.6f}'}, 0.01)
