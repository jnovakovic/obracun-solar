import io
import os
import time
from pathlib import Path

import folium
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_folium import st_folium

import energy_billing as eb

# Model assumptions
SETTLEMENT = dict(threshold_on_import=False,     # 3,000 kWh threshold counts netted kWh in both schemes
                  pkc_includes_subsidy=False)    # PKC = energy price weighted by VT/NT imports only
FINANCE = dict(discount_first_year=False,        # year y discounted with (1+r)^(y-1)
               escalate_all_prices=True,         # all price items grow with the escalation rate
               inflate_inverter=False,           # inverter replacement at today's cost
               **SETTLEMENT)

st.set_page_config(page_title="Kalkulator isplativosti SE", page_icon="☀️",
                   layout="wide", initial_sidebar_state="expanded")

# All series use one fixed, non-leap calendar in CET (UTC+1, no DST), 15-minute resolution.
REF_YEAR = 2019
N15 = 35040
INDEX_15 = pd.date_range(f"{REF_YEAR}-01-01", periods=N15, freq="15min")
MONTHS = eb.MJESECI
MONTH_ABBR = ['Sij', 'Velj', 'Ožu', 'Tra', 'Svi', 'Lip', 'Srp', 'Kol', 'Ruj', 'Lis', 'Stu', 'Pro']
TARIFFS = ["Bijeli (VT_NT)", "Plavi (JT)", "Crveni (VT_NT)", "Crni (JT)"]
LABEL = {'noPV': 'Bez SE', 'month': 'Mjesečno netiranje', '15min': 'Neto obračun (15 min)'}
COLOR = {'noPV': '#a3a3a3', 'month': '#2ca02c', '15min': '#2c5ea0', 'pv': '#FFA500', 'load': '#1f77b4'}
CUSTOMER = {
    "Kućanstvo – samoopskrba": 1.0,
    "Poduzetništvo": eb.FACTOR_BUSINESS,
}
TRACKING = {"Fiksni položaj modula": 0, "Horizontalna os S-J": 1, "Dvoosni": 2, "Vertikalna os": 3, "Horizontalna os I-Z": 4}
PATTERNS = ["Primjer kućanstva", "Jednoliko distribuirana", "Veća potrošnja tijekom dana",
            "Veća potrošnja tijekom večeri", "Sezonska (veća potrošnja ljeti)", "Sezonska (veća potrošnja zimi)"]


def show(fig):
    st.plotly_chart(fig)


def years_text(v):
    return f"{v:.1f} g." if v is not None else "Ne isplati se"


HERE = Path(__file__).resolve().parent                 # data files are next to the app (or one folder up)
os.chdir(HERE if (HERE / 'mobile_styles.css').exists() else HERE.parent)

with open('mobile_styles.css', 'r') as f:
    st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

# --------------------------------------------------------------------------- cached computations
@st.cache_data(show_spinner=False, ttl=24 * 3600)
def fetch_pvgis(lat, lon, year, peakpower, loss, angle, aspect, tech, mounting, tracking):
    """Hourly PV output from PVGIS 5.3. Time stamps are UTC at HH:10 (PVGIS convention)."""
    params = {"lat": lat, "lon": lon, "startyear": year, "endyear": year, "peakpower": peakpower, "loss": loss,
              "angle": angle, "aspect": aspect, "pvtechchoice": tech, "mountingplace": mounting,
              "trackingtype": tracking, "optimalinclination": 0, "optimalangles": 0, "pvcalculation": 1,
              "components": 0, "outputformat": "json", "browser": 0}
    r = requests.get("https://re.jrc.ec.europa.eu/api/v5_3/seriescalc", params=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"PVGIS: {r.status_code} - {r.text[:300]}")
    hourly = r.json().get("outputs", {}).get("hourly", [])
    if not hourly:
        raise RuntimeError("PVGIS nije vratio satne podatke.")
    df = pd.DataFrame(hourly)
    df['time'] = pd.to_datetime(df['time'], format='%Y%m%d:%H%M')
    return df.set_index('time')


def pvgis_to_15min(raw):
    """PVGIS hourly (UTC) -> 15-minute series on the CET reference calendar.
    The value stamped HH:10 UTC is the energy of hour HH..HH+1 UTC = HH+1..HH+2 CET, so the series moves one
    hour later; 29 February is dropped so every year maps onto the same 8,760 hours as the load profiles."""
    raw = raw[~((raw.index.month == 2) & (raw.index.day == 29))]
    if len(raw) != 8760:
        raise ValueError(f"Očekivano 8760 satnih vrijednosti, dobiveno {len(raw)}.")
    p_kw = raw['P'].to_numpy(dtype=float) / 1000
    p_kw = np.r_[0.0, p_kw[:-1]]                       # UTC -> CET
    p15 = np.repeat(p_kw, 4)
    return pd.DataFrame({'P': p15, 'ac_power_kw': p15 * 0.25}, index=INDEX_15)   # P in kW, ac_power_kw in kWh/15 min


@st.cache_data(show_spinner=False)
def predefined_profile(pattern, annual_kwh):
    h, m = INDEX_15.hour.to_numpy(), INDEX_15.month.to_numpy()
    if pattern == "Primjer kućanstva":
        x = pd.read_csv("Load_data_15min.csv", header=None)[0].to_numpy(dtype=float)[:N15]
    elif pattern == "Veća potrošnja tijekom dana":
        x = np.where((h >= 8) & (h < 18), 1.5, 0.5)
    elif pattern == "Veća potrošnja tijekom večeri":
        x = np.where((h >= 17) & (h < 23), 2.0, 0.5)
    elif pattern == "Sezonska (veća potrošnja ljeti)":
        x = np.where((m >= 5) & (m <= 9), 1.5, 0.5)
    elif pattern == "Sezonska (veća potrošnja zimi)":
        x = np.where((m <= 3) | (m >= 11), 1.5, 0.5)
    else:
        x = np.ones(N15)
    return x * annual_kwh / x.sum()


@st.cache_data(show_spinner=False)
def read_upload(data, name, skip_rows, has_header, column, unit, decimal):
    """Returns (kWh per 15 min, notes). Accepts 15-min (35,040) or hourly (8,760) values, leap years included."""
    buf = io.BytesIO(data)
    header = 0 if has_header else None
    if name.lower().endswith('.csv'):
        first = next((ln for ln in data.decode('utf-8', 'ignore').splitlines()[skip_rows:] if ln.strip()), '')
        sep = ';' if ';' in first else '\t' if '\t' in first else (';' if decimal == ',' else ',')
        df = pd.read_csv(buf, header=header, skiprows=skip_rows, sep=sep, decimal=decimal)
    else:
        df = pd.read_excel(buf, header=header, skiprows=skip_rows)
    s = df[column] if has_header else df.iloc[:, int(column)]
    if s.dtype == object or pd.api.types.is_string_dtype(s):
        s = s.astype(str).str.replace(',', '.', regex=False)
    v = pd.to_numeric(s, errors='coerce').dropna().to_numpy(dtype=float)
    notes = []
    if len(v) in (8784, 35136):                       # leap year: drop 29 February
        per_day = 24 if len(v) == 8784 else 96
        v = np.r_[v[:59 * per_day], v[60 * per_day:]]
        notes.append("Prijestupna godina: uklonjen je 29. veljače.")
    if len(v) == 8760:
        kwh_h = v if unit == "kWh" else v * 1.0        # mean kW over an hour = kWh in that hour
        notes.append("Prepoznati su satni podaci; svaki sat je jednoliko podijeljen na četiri 15-minutna intervala.")
        return np.repeat(kwh_h / 4, 4), notes
    kwh = v if unit == "kWh" else v * 0.25
    if len(kwh) < N15:
        notes.append(f"Datoteka ima {len(kwh)} vrijednosti; ponavljaju se do 35.040 vrijednosti.")
        kwh = np.tile(kwh, int(np.ceil(N15 / len(kwh))))[:N15]
    elif len(kwh) > N15:
        notes.append(f"Datoteka ima {len(kwh)} vrijednosti; koristi se prvih 35.040.")
        kwh = kwh[:N15]
    return kwh, notes


@st.cache_data(show_spinner=False)
def run_settlement(pv, load, tariff, k, sub_kwh):
    prices = pd.read_csv(f"{tariff}.csv")
    prod = pd.DataFrame({'ac_power_kw': pv}, index=INDEX_15)
    cons = pd.DataFrame({'consumption_kw': load}, index=INDEX_15)
    zero = pd.DataFrame({'ac_power_kw': np.zeros(N15)}, index=INDEX_15)
    out = {'noPV': eb.izvrši_obracun(zero, cons, prices, sub_kwh, 'month'),
           'month': eb.izvrši_obracun(prod, cons, prices, sub_kwh, 'month'),
           '15min': eb.izvrši_obracun(prod, cons, prices, sub_kwh, '15min', k, **SETTLEMENT)}
    return prices, out


@st.cache_data(show_spinner=False)
def run_finance(pv, load, tariff, k, sub_kwh, capacity_kw, params):
    prices = pd.read_csv(f"{tariff}.csv")
    return eb.analiza_isplativosti(pv, load, INDEX_15, prices, capacity_kw, sub_kWh=sub_kwh, kSO=k, **params, **FINANCE)


def show_bill(r):
    num = st.column_config.NumberColumn
    st.dataframe(r.loc[1:9, ['Opis', 'Iznos EUR']], hide_index=True,
                 column_config={'Iznos EUR': num(format="%.2f")})
    st.dataframe(r.loc[12:15, ['Opis', 'Stanje od', 'Stanje do', 'Potrošak']], hide_index=True,
                 column_config={'Stanje od': num(format="%.2f"), 'Stanje do': num(format="%.2f"), 'Potrošak': num(format="%.0f")})
    st.dataframe(r.loc[16:33, ['Opis', 'Količina', 'Jedinica mjere', 'Cijena EUR/kWh', 'Iznos EUR']], hide_index=True,
                 column_config={'Količina': num(format="%.0f"), 'Cijena EUR/kWh': num(format="%.6f"), 'Iznos EUR': num(format="%.2f")})


# --------------------------------------------------------------------------- page
ss = st.session_state
ss.setdefault('lat', 43.5147)
ss.setdefault('lon', 16.4435)
if 'pending_click' in ss:                               # apply a map click before the inputs are drawn
    ss['lat'], ss['lon'] = ss.pop('pending_click')

st.title("☀️ Kalkulator isplativosti solarne elektrane")
st.markdown("""
Usporedba isplativosti male solarne elektrane kućanstva za dva načina obračuna električne energije:
**mjesečno netiranje** (zahtjevi za priključenje predani do 31. 12. 2025., čl. 51. st. 21. ZOIEVUK-a) i
**neto obračun** (od 1. 1. 2026., čl. 51. st. 7.), kod kojeg se preuzeta i predana energija određuju u
15-minutnim intervalima, a predana energija vrednuje po cijeni opskrbe umanjenoj prema omjeru preuzete i predane energije.
""")

tabs = st.tabs(["Lokacija & Sustav", "Proizvodnja", "Potrošnja", "Godišnji račun", "Financijska analiza", "Rezultati"])

# --------------------------------------------------------------------------- 0 location & system
with tabs[0]:
    st.header("Lokacija & parametri sustava")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Lokacija")
        latitude = st.number_input("Geografska širina", min_value=-90.0, max_value=90.0, step=0.01, format="%.4f", key='lat')
        longitude = st.number_input("Geografska dužina", min_value=-180.0, max_value=180.0, step=0.01, format="%.4f", key='lon')
        m = folium.Map(location=[latitude, longitude], zoom_start=10)
        folium.Marker([latitude, longitude], tooltip="Lokacija elektrane",
                      icon=folium.Icon(color="orange", icon="sun", prefix="fa")).add_to(m)
        st.caption("Kliknite na kartu za odabir lokacije.")
        map_data = st_folium(m, height=300, use_container_width=True, returned_objects=["last_clicked"], key='map')
        click = (map_data or {}).get("last_clicked")
        if click:
            c = (round(click["lat"], 4), round(click["lng"], 4))
            if c != ss.get('last_click_seen'):
                ss['last_click_seen'] = c
                ss['pending_click'] = c
                st.rerun()
    with c2:
        st.subheader("Parametri solarne elektrane")
        system_capacity_kw = st.number_input("Instalirana snaga solarne elektrane (kW)", min_value=0.5, max_value=100.0, value=4.5, step=0.1)
        module_type = st.selectbox("Tip modula", ["crystSi", "CIS", "CdTe"], index=0)
        losses = st.slider("Gubici u sustavu (%)", 0, 30, 14, 1)
        tilt = st.number_input("Kut nagiba modula (°)", min_value=0, max_value=90, value=20, step=1)
        azimuth = st.number_input("Azimut (°, 0 = jug, -90 = istok, 90 = zapad)", min_value=-180, max_value=180, value=0, step=1)
        tracking = st.selectbox("Tip praćenja sunca", list(TRACKING), index=0)


# --------------------------------------------------------------------------- 1 production
with tabs[1]:
    st.header("Proizvodnja energije solarne elektrane")
    st.write("Satna proizvodnja iz PVGIS-a (EU JRC), pretvorena iz UTC-a u srednjoeuropsko vrijeme i raspodijeljena na 15-minutne intervale.")
    pv_year = st.selectbox("Meteorološka godina (PVGIS)", list(range(2005, 2024)), index=2019 - 2005,
                           help="2019. je godina čija je proizvodnja najbliža desetogodišnjem prosjeku izmjerenom na FESB-u.")
    pv_params = (round(latitude, 4), round(longitude, 4), int(pv_year), float(system_capacity_kw), int(losses), int(tilt),
                 int(azimuth), module_type, "free", TRACKING[tracking])
    if st.button("Izračunaj proizvodnju SE", type="primary"):
        with st.spinner("Dohvaćam podatke iz PVGIS-a..."):
            try:
                raw = fetch_pvgis(*pv_params)
                ss['production_data'] = pvgis_to_15min(raw)
                ss['pv_params_used'] = pv_params
            except Exception as e:
                st.error(f"Greška pri izračunu proizvodnje SE: {e}")

    production_data = ss.get('production_data')
    if production_data is None:
        st.info("Kliknite na 'Izračunaj proizvodnju SE' kako biste dobili procjenu proizvodnje.")
    else:
        used = ss.get('pv_params_used', pv_params)
        if used != pv_params:
            st.warning("Parametri sustava su promijenjeni. Ponovno kliknite 'Izračunaj proizvodnju SE'.")
        total = production_data['ac_power_kw'].sum()
        cap = used[3]
        c1, c2, c3 = st.columns(3)
        c1.metric("Ukupna godišnja proizvodnja", f"{total:,.0f} kWh")
        c1.metric("Meteorološka godina", f"{used[2]}")
        c2.metric("Specifična proizvodnja", f"{total / cap:,.0f} kWh/kW")
        c2.metric("Faktor iskorištenja", f"{100 * total / (cap * 8760):.1f} %")
        c3.metric("Prosječna dnevna proizvodnja", f"{total / 365:.1f} kWh")
        c3.metric("Vršna satna snaga", f"{production_data['P'].max():.2f} kW")
        monthly = production_data['ac_power_kw'].groupby(INDEX_15.month).sum()
        fig = px.bar(x=MONTH_ABBR, y=monthly.to_numpy(), labels={'x': 'Mjesec', 'y': 'Energija (kWh)'},
                     title='Mjesečna proizvodnja', color_discrete_sequence=[COLOR['pv']])
        fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=380)
        show(fig)

# --------------------------------------------------------------------------- 2 consumption
consumption_df = None
with tabs[2]:
    st.header("Potrošnja električne energije kućanstva")
    mode = st.radio("Način unosa potrošnje:", ["Predefinirani profil", "Uploadirajte vlastite podatke"], horizontal=True)
    load = None
    if mode == "Predefinirani profil":
        c1, c2 = st.columns(2)
        pattern = c1.selectbox("Uzorak potrošnje energije", PATTERNS, index=0)
        default_annual = float(np.round(pd.read_csv("Load_data_15min.csv", header=None)[0].sum(), 1))
        annual = c2.number_input("Godišnja potrošnja električne energije (kWh)", min_value=500.0, max_value=100000.0,
                                 value=default_annual, step=100.0)
        load = predefined_profile(pattern, annual)
    else:
        with st.expander("Format datoteke"):
            st.markdown("""
- CSV ili Excel, jedan stupac s vrijednostima potrošnje (bez datuma ili uz odabir stupca)
- **35.040** 15-minutnih vrijednosti ili **8.760** satnih vrijednosti za jednu godinu (prijestupna godina je dopuštena)
- prva vrijednost odgovara intervalu 1. 1. 00:00 po srednjoeuropskom (zimskom) vremenu
- vrijednosti u **kWh po intervalu** ili kao **prosječna snaga u kW**
- ako je vrijednosti manje, ponavljaju se do pune godine
""")
        uploaded = st.file_uploader("Izaberite datoteku", type=["csv", "xlsx", "xls"])
        if uploaded is not None:
            c1, c2, c3 = st.columns(3)
            skip = c1.number_input("Preskoči redaka", min_value=0, value=0)
            has_header = c1.checkbox("Datoteka ima naslove stupaca", value=False)
            column = c2.text_input("Naslov stupca", value="potrošnja") if has_header else c2.number_input("Broj stupca (0 = prvi)", min_value=0, value=0)
            unit = c3.radio("Jedinica", ["kWh", "kW"], horizontal=True)
            decimal = c3.radio("Decimalni separator", [".", ","], horizontal=True)
            try:
                load, notes = read_upload(uploaded.getvalue(), uploaded.name, int(skip), has_header, column, unit, decimal)
                for n in notes:
                    st.info(n)
            except Exception as e:
                st.error(f"Greška u obradi datoteke: {e}")
        else:
            st.info("Uploadirajte datoteku s podacima o potrošnji.")

    if load is not None:
        consumption_df = pd.DataFrame({'consumption_kw': load}, index=INDEX_15)   # kWh per 15 min
        total_load = load.sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Ukupna godišnja potrošnja", f"{total_load:,.0f} kWh")
        c2.metric("Prosječna dnevna potrošnja", f"{total_load / 365:.1f} kWh")
        c3.metric("Vršna 15-minutna snaga", f"{load.max() * 4:.2f} kW")
        if production_data is not None:
            pv = production_data['ac_power_kw'].to_numpy()
            self_cons = np.minimum(pv, load).sum()
            c1.metric("Udio vlastite potrošnje proizvodnje", f"{100 * self_cons / pv.sum():.1f} %")
            c2.metric("Pokrivenost potrošnje iz SE", f"{100 * self_cons / total_load:.1f} %")

        month_idx = INDEX_15.month
        df_m = pd.DataFrame({'Mjesec': MONTH_ABBR, 'Potrošnja': pd.Series(load).groupby(month_idx).sum().to_numpy()})
        if production_data is not None:
            df_m['Proizvodnja'] = production_data['ac_power_kw'].groupby(month_idx).sum().to_numpy()
        df_long = df_m.melt(id_vars='Mjesec', var_name='Vrsta', value_name='Energija (kWh)')
        fig = px.bar(df_long, x='Mjesec', y='Energija (kWh)', color='Vrsta', barmode='group',
                     title='Mjesečna proizvodnja i potrošnja',
                     color_discrete_map={'Proizvodnja': COLOR['pv'], 'Potrošnja': COLOR['load']})
        fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=420)
        show(fig)

        def heatmap(values, title):
            pivot = pd.Series(values * 4).groupby([INDEX_15.hour, INDEX_15.month]).mean().unstack()
            f = px.imshow(pivot, labels=dict(x="Mjesec", y="Sat", color="Prosj. snaga (kW)"),
                          x=MONTH_ABBR, y=[f"{h}:00" for h in range(24)], color_continuous_scale='YlOrRd',
                          title=title, aspect='auto')
            f.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=450)
            show(f)

        heatmap(load, "Prosječna potrošnja po satu i mjesecu")
        if production_data is not None:
            heatmap(production_data['ac_power_kw'].to_numpy(), "Prosječna proizvodnja po satu i mjesecu")

        st.subheader("Prosječni dnevni profil")
        sel = st.selectbox("Mjesec", range(1, 13), format_func=lambda x: MONTHS[x - 1], index=6)
        mm = INDEX_15.month == sel
        prof = pd.DataFrame({'Potrošnja': pd.Series(load[mm] * 4).groupby(INDEX_15[mm].hour).mean()})
        if production_data is not None:
            prof['Proizvodnja'] = pd.Series(production_data['ac_power_kw'].to_numpy()[mm] * 4).groupby(INDEX_15[mm].hour).mean()
        fig = px.line(prof, markers=True, labels={'index': 'Sat', 'value': 'Prosječna snaga (kW)', 'variable': ''},
                      title=f'Prosječni dnevni profil – {MONTHS[sel - 1]}',
                      color_discrete_map={'Proizvodnja': COLOR['pv'], 'Potrošnja': COLOR['load']})
        fig.update_layout(xaxis=dict(tickmode='linear', dtick=2), margin=dict(l=10, r=10, t=40, b=10), height=380)
        show(fig)

ready = production_data is not None and consumption_df is not None

# --------------------------------------------------------------------------- 3 annual bill
settlement = None
with tabs[3]:
    st.header("Godišnji račun")
    c1, c2, c3 = st.columns(3)
    tariff = c1.selectbox("Tarifni model", TARIFFS, index=0)
    customer = c2.selectbox("Kategorija kupca (neto obračun)", list(CUSTOMER), index=0)
    is_business = customer.startswith("Poduzetništvo")
    k_export = c2.number_input("Faktor cijene predane energije (kSO)", min_value=0.0, max_value=1.0,
                               value=CUSTOMER[customer], step=0.05, key=f"k_{customer}", disabled=is_business,
                               help="HERA: 1 za kućanstva (Poticajni okvir, 16. 7. 2026.). Za poduzetništvo zakon propisuje 0,9.")
    sub_kwh = c3.number_input("Prag šestomjesečne potrošnje (kWh)", min_value=0, max_value=100000, value=3000, step=100,
                              help="Iznad praga cijena energije je viša za postotak iz cjenika (Sub_increase).")
    if is_business:
        k_export = eb.FACTOR_BUSINESS

    if not ready:
        st.warning("Izračunajte proizvodnju SE (kartica Proizvodnja) i odaberite potrošnju (kartica Potrošnja).")
    else:
        prices_df, settlement = run_settlement(production_data['ac_power_kw'].to_numpy(), consumption_df['consumption_kw'].to_numpy(),
                                               tariff, float(k_export), int(sub_kwh))
        totals = {s: settlement[s][2].loc['Year', 'Bill'] for s in ('noPV', 'month', '15min')}
        c1, c2, c3 = st.columns(3)
        c1.metric("Bez SE", f"{totals['noPV']:,.2f} EUR")
        c2.metric(LABEL['month'], f"{totals['month']:,.2f} EUR", delta=f"{totals['month'] - totals['noPV']:,.2f} EUR", delta_color="inverse")
        c3.metric(LABEL['15min'], f"{totals['15min']:,.2f} EUR", delta=f"{totals['15min'] - totals['noPV']:,.2f} EUR", delta_color="inverse")

        df_b = pd.DataFrame({'Mjesec': MONTH_ABBR})
        for s in ('noPV', 'month', '15min'):
            df_b[LABEL[s]] = [settlement[s][1][mj].loc[9, 'Iznos EUR'] for mj in MONTHS]
        fig = px.bar(df_b.melt(id_vars='Mjesec', var_name='Obračun', value_name='EUR'), x='Mjesec', y='EUR', color='Obračun',
                     barmode='group', title='Mjesečni računi za električnu energiju',
                     color_discrete_map={LABEL[s]: COLOR[s] for s in LABEL})
        fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=420)
        show(fig)

        c1, c2 = st.columns(2)
        for col, s in ((c1, 'month'), (c2, '15min')):
            with col:
                st.write(f"**Godišnji račun – {LABEL[s]}**")
                g = settlement[s][3]
                show(eb.plot_bill_style_plotly(g[g.index < 10]))
                st.download_button("Preuzmi godišnji račun (CSV)", g.to_csv().encode('utf-8'),
                                   f"godisnji_racun_{s}.csv", "text/csv", key=f"dl_{s}")

        st.subheader("Mjesečni računi")
        mj = st.selectbox("Mjesec računa", MONTHS, index=6)
        c1, c2 = st.columns(2)
        for col, s in ((c1, 'month'), (c2, '15min')):
            with col:
                st.write(f"**{mj} – {LABEL[s]}**")
                show_bill(settlement[s][1][mj])

# --------------------------------------------------------------------------- 4 financial analysis
with tabs[4]:
    st.header("Financijska analiza")
    st.write("Isplativost ulaganja kod mjesečnog netiranja i neto obračuna. "
             "Mjesečno netiranje pretpostavljeno je kroz cijeli vijek trajanja elektrane.")
    c1, c2 = st.columns(2)
    with c1:
        cost_per_kw = st.number_input("Trošak izgradnje solarne elektrane (€/kW)", min_value=300, max_value=5000, value=1000, step=10)
        incentive = st.slider("Dobiveni poticaji (% troška izgradnje)", 0, 100, 0, 5)
        loan_pct = st.slider("Udio financiranja kreditom (%)", 0, 100, 0, 5)
        loan_rate = st.slider("Kamatna stopa kredita (%)", 0.0, 10.0, 3.0, 0.1)
        loan_years = st.slider("Rok otplate kredita (godine)", 1, 25, 10, 1)
        discount = st.slider("Diskontna stopa (%)", 0.0, 10.0, 4.0, 0.1)
    with c2:
        inverter_cost = st.number_input("Trošak zamjene invertera (€)", min_value=0.0, max_value=5000.0, value=500.0, step=10.0)
        inverter_year = st.slider("Godina zamjene invertera", 1, 25, 10, 1)
        lifetime = st.slider("Vijek trajanja sustava (godine)", 10, 30, 25, 1)
        degradation = st.slider("Godišnja degradacija panela (%)", 0.0, 2.0, 0.8, 0.1)
        om = st.slider("Održavanje i osiguranje (% troška izgradnje godišnje)", 0.0, 5.0, 0.5, 0.1)
        growth = st.slider("Godišnji rast cijena električne energije (%)", 0.0, 10.0, 2.0, 0.5)
        inflation = st.slider("Godišnja stopa inflacije (%)", 0.0, 10.0, 2.0, 0.5)

    if not ready:
        st.warning("Izračunajte proizvodnju SE i odaberite potrošnju.")
    else:
        t0 = time.time()
        params = dict(cost_per_kw=float(cost_per_kw), incentive_pct=float(incentive), loan_pct=float(loan_pct),
                      loan_rate_pct=float(loan_rate), loan_years=int(loan_years), discount_pct=float(discount),
                      inverter_cost=float(inverter_cost), inverter_year=int(inverter_year), lifetime=int(lifetime),
                      degradation_pct=float(degradation), om_pct=float(om), price_growth_pct=float(growth),
                      inflation_pct=float(inflation))
        res = run_finance(production_data['ac_power_kw'].to_numpy(), consumption_df['consumption_kw'].to_numpy(),
                          tariff, float(k_export), int(sub_kwh), float(ss.get('pv_params_used', pv_params)[3]), params)
        costs = res['costs']
        st.subheader("Financijski pokazatelji")
        c1, c2, c3 = st.columns(3)
        c1.metric("Ukupni trošak SE", f"€{costs['total']:,.0f}")
        c1.metric("Trošak nakon poticaja", f"€{costs['net']:,.0f}")
        c1.metric("Vlastita sredstva", f"€{costs['equity']:,.0f}")
        if costs['loan'] > 0:
            c1.metric("Godišnja rata kredita", f"€{costs['loan_payment']:,.0f}")
        for col, s in ((c2, 'month'), (c3, '15min')):
            r = res[s]
            col.write(f"**{LABEL[s]}**")
            col.metric("Ušteda na računu (1. godina)", f"€{r['first_year_saving']:,.0f}")
            col.metric("Diskontirani povrat ulaganja", years_text(r['payback']))
            col.metric("Neto sadašnja vrijednost (NPV)", f"€{r['npv']:,.0f}")
            col.metric("Interna stopa povrata (IRR)", f"{100 * r['irr']:.1f} %" if r['irr'] is not None else "–")

        st.subheader(f"{lifetime}-godišnja analiza novčanih tokova")
        yrs = list(range(0, lifetime + 1))
        fig = go.Figure()
        for s in ('month', '15min'):
            fig.add_trace(go.Bar(x=yrs, y=np.r_[-costs['equity'], res['table'][f'Disk_tok_{s}']],
                                 name=f'Godišnji diskontirani tok ({LABEL[s]})', marker_color=COLOR[s], opacity=0.55))
        for s in ('month', '15min'):
            fig.add_trace(go.Scatter(x=yrs, y=res[s]['cumulative'], name=f'Kumulativno ({LABEL[s]})',
                                     line=dict(color=COLOR[s], width=3), mode='lines+markers'))
        fig.add_hline(y=0, line_color='#8a8a84', line_width=1)
        fig.update_layout(xaxis=dict(title='Godina'), yaxis=dict(title='€'), barmode='group', hovermode='x unified',
                          legend=dict(orientation='h', x=0.5, xanchor='center', y=1.12), margin=dict(l=10, r=10, t=60, b=10), height=480)
        show(fig)
        with st.expander("Tablica novčanih tokova"):
            st.dataframe(res['table'].round(2))
            st.download_button("Preuzmi tablicu (CSV)", res['table'].to_csv().encode('utf-8'), "novcani_tokovi.csv", "text/csv")
        st.caption(f"Izračun trajao {time.time() - t0:.2f} s.")

# --------------------------------------------------------------------------- 5 results
with tabs[5]:
    st.header("Rezultati")
    if settlement is None:
        st.info("Rezultati se prikazuju nakon izračuna godišnjeg računa.")
    else:
        pv = production_data['ac_power_kw'].to_numpy()
        load = consumption_df['consumption_kw'].to_numpy()
        mon = INDEX_15.month
        net = pv - load
        me = pd.DataFrame({'production': pv, 'consumption': load, 'net': net, 'self': np.minimum(pv, load),
                           'exported': np.clip(net, 0, None), 'imported': np.clip(-net, 0, None)}).groupby(mon).sum()
        me.index = MONTH_ABBR
        sell_15 = [settlement['15min'][1][mj].loc[32, 'Cijena EUR/kWh'] for mj in MONTHS]
        sell_month = settlement['month'][1]['Siječanj'].loc[32, 'Cijena EUR/kWh']
        buy_vt = float(prices_df.loc[0, 'Total_HT'])

        st.subheader("Cijena preuzete i predane energije u višoj tarifi (VT), 1. godina")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=MONTH_ABBR, y=[buy_vt] * 12, name='Preuzeta energija (VT, s naknadama i PDV-om)',
                                 line=dict(color='#d62728'), mode='lines+markers'))
        fig.add_trace(go.Scatter(x=MONTH_ABBR, y=[sell_month] * 12, name=f'Višak – {LABEL["month"]} (0,8 · Cp)',
                                 line=dict(color=COLOR['month']), mode='lines+markers'))
        fig.add_trace(go.Scatter(x=MONTH_ABBR, y=sell_15, name=f'Predana energija – {LABEL["15min"]}',
                                 line=dict(color=COLOR['15min']), mode='lines+markers'))
        fig.update_layout(yaxis=dict(title='EUR/kWh', rangemode='tozero'), hovermode='x unified',
                          legend=dict(x=0.01, y=0.99), margin=dict(l=10, r=10, t=10, b=10), height=420)
        show(fig)
        st.write("Kod neto obračuna vrijednost predane energije pada u mjesecima u kojima kućanstvo preda više energije nego što preuzme (omjer Ep/Ei < 1).")

        st.subheader(f"Mjesečna bilanca – {LABEL['month']}")
        st.write(f"Netiraju se mjesečne količine po tarifama; samo mjesečni višak u tarifi plaća se po {sell_month:.3f} EUR/kWh (VT), "
                 f"a ušteđeni kWh vrijedi punu cijenu preuzete energije ({buy_vt:.3f} EUR/kWh u VT).")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=me.index, y=me['production'], name='Proizvodnja', marker_color=COLOR['month']))
        fig.add_trace(go.Bar(x=me.index, y=-np.maximum(0, me['net']), name='Neto višak', marker_color=COLOR['15min'],
                             marker_pattern_shape='/'))
        fig.add_trace(go.Bar(x=me.index, y=-np.minimum(0, me['net']), name='Neto manjak', marker_color='#d62728'))
        fig.add_trace(go.Scatter(x=me.index, y=me['consumption'], name='Potrošnja', line=dict(color='#ff7f0e'), mode='lines+markers'))
        fig.update_layout(yaxis=dict(title='Energija (kWh)'), barmode='relative', hovermode='x unified',
                          legend=dict(x=0.01, y=0.99), margin=dict(l=10, r=10, t=10, b=10), height=420)
        show(fig)

        st.subheader(f"Mjesečna bilanca – {LABEL['15min']}")
        st.write("Sva energija preuzeta iz mreže plaća se po punoj cijeni, a sva predana energija vrednuje se po nižoj cijeni predane energije.")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=me.index, y=me['self'], name='Vlastita potrošnja proizvodnje', marker_color=COLOR['month']))
        fig.add_trace(go.Bar(x=me.index, y=me['imported'], name='Preuzeto iz mreže', marker_color='#d62728'))
        fig.add_trace(go.Bar(x=me.index, y=me['exported'], name='Predano u mrežu', marker_color=COLOR['15min']))
        fig.add_trace(go.Scatter(x=me.index, y=me['consumption'], name='Potrošnja', line=dict(color='#ff7f0e'), mode='lines+markers'))
        fig.update_layout(yaxis=dict(title='Energija (kWh)'), barmode='stack', hovermode='x unified',
                          legend=dict(x=0.01, y=0.99), margin=dict(l=10, r=10, t=10, b=10), height=420)
        show(fig)
