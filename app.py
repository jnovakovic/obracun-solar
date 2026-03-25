import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from energy_billing import izvrši_obracun, plot_bill_style, display_bill_table, plot_bill_style_plotly,plot_bill_style2, plot_bill_style3   
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pvlib
from pvlib.location import Location
from pvlib.pvsystem import PVSystem
from pvlib.modelchain import ModelChain
from pvlib.temperature import TEMPERATURE_MODEL_PARAMETERS
import folium
from streamlit_folium import st_folium
import os
import pdb
from pvlib.iotools import get_pvgis_tmy
import requests
import time


# Set page configuration
st.set_page_config(
    page_title="Kalkulator isplativosti solarne elektrane",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded"
)

#reset load data
st.session_state['consumption_data'] = None

# Load custom CSS for mobile optimization
with open('mobile_styles.css', 'r') as f:
    css = f.read()
st.markdown(f'<style>{css}</style>', unsafe_allow_html=True)

# Add JavaScript for mobile detection
st.markdown("""
<script>
    // Check if the device is mobile
    if (/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)) {
        // Set a session state variable to indicate mobile device
        const data = {
            _is_mobile: true
        };
        
        // Send the data to Streamlit
        window.parent.postMessage({
            type: "streamlit:setComponentValue",
            value: data
        }, "*");
    }
</script>
""", unsafe_allow_html=True)

# App title and description
st.title("☀️ Kalkulator isplativosti solarne elektrane")
st.markdown("""
Aplikacija  daje usporedbu profitabilnosti male solarne elektrane pod različitim načinima obračuna troška električne energije (mjesečno netiranje vs. 15 minutno netiranje energije). \n
Unesite svoju lokaciju, specifikacije sustava i financijske parametre kako biste vidjeli detaljne rezultate i njihove prikaze.
""")

# Create sidebar for inputs
st.sidebar.header("Ulazni parametri")

# Main content will be organized in tabs
tabs = st.tabs(["Lokacija & Sustav","Proizvodnja","Potrošnja", "Godišnji račun", "Financijska analiza", "Rezultati"])

# Initialize session state for latitude and longitude if not already set
if 'latitude' not in st.session_state:
    st.session_state.latitude = 43.5147  # Split
if 'longitude' not in st.session_state:
    st.session_state.longitude = 16.4435

# Callbacks to update session state when inputs change
def update_latitude():
    st.session_state.latitude = st.session_state.lat_input

def update_longitude():
    st.session_state.longitude = st.session_state.lon_input

with tabs[0]:
    st.header("Lokacija & parametri sustava")
    st.write("Izaberite svoju lokaciju i unesite parametre solarne elektrane.")
    
    # Location section
    st.subheader("Lokacija")
    
    # Use a single column on mobile, two columns on larger screens
    use_cols = st.columns([1]) if st.session_state.get('_is_mobile', False) else st.columns(2)
    
    with use_cols[0]:
        default_lat = 43.5147  # Split
        default_lon = 16.4435
        latitude = st.number_input("Latitude", min_value=-90.0, max_value=90.0, value=st.session_state.latitude, step=0.01, format="%.4f")
        longitude = st.number_input("Longitude", min_value=-180.0, max_value=180.0, value=st.session_state.longitude, step=0.01, format="%.4f")
        altitude = st.number_input("Altitude (m)", min_value=0, max_value=5000, value=10, step=10)
        timezone = st.selectbox("Timezone", options=["Europe/Berlin","Europe/London","US/Eastern", "US/Central", "US/Mountain", "US/Pacific",   "Asia/Tokyo", "Australia/Sydney"], index=0)
    

        # Create a map centered at the current coordinates from session state
        #m = folium.Map(location=[st.session_state.latitude, st.session_state.longitude], zoom_start=10,tiles='https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{z}/{x}/{y}.png',  attr='© CartoDB')
        #folium.Marker(
        #[st.session_state.latitude, st.session_state.longitude],
        #popup="Solar Installation Site",
        #tooltip="Solar Installation Site",
        #icon=folium.Icon(color="orange", icon="sun", prefix="fa")
        #).add_to(m) 

        m = folium.Map(location=[latitude, longitude], zoom_start=10)
        folium.Marker(
            [latitude, longitude],
            popup="Solar Installation Site",
            tooltip="Solar Installation Site",
            icon=folium.Icon(color="orange", icon="sun", prefix="fa")
        ).add_to(m)
        
        # Display the map with smaller size for mobile
        st.write("Lokacija:")
        map_data = st_folium(m, width=900, height=300, returned_objects=["last_clicked"])

        # If a click is detected, update session state and rerun to refresh inputs/map
        if map_data and map_data.get("last_clicked"):
            st.session_state.latitude = map_data["last_clicked"]["lat"]
            st.session_state.longitude = map_data["last_clicked"]["lng"]
            st.rerun()
    
    # System configuration section
    st.subheader("Parametri solarne elektrane")
    
    # Use a single column on mobile, two columns on larger screens
    col1, col2 = st.columns(1) if st.session_state.get('_is_mobile', False) else st.columns(2)
    
    with col1:
        system_capacity_kw = st.number_input("Instalirana snaga solarne elektrane  (kW)", min_value=0.5, max_value=100.0, value=4.5, step=0.1)
        #module_type = st.selectbox("Tip modula", options=["monoSi", "multiSi", "cSi", "cis", "CIGS", "CdTe", "amorphous"], index=0)
        module_type = st.selectbox("Tip modula", options=["crystSi", "CIS", "CdTe"], index=0)
        total_system_losses_percent = st.slider("Gubici u sustavu (%)", min_value=0, max_value=30, value=14, step=1)
        
    with col2:
        tilt = st.number_input("Kut nagiba modula (stupnjevi)", min_value=0, max_value=90, value=20, step=1)
        azimuth = st.number_input("Azimut (stupnjevi, 0=Jug)", min_value=-180, max_value=180, value=0, step=1)
        tracking_type = st.selectbox("Tip praćenja sunca ", options=["Fiksni položaj modula","Horizontalna os S-J", "Dvoosni", "Vertikalna os","Horizontalno I-Z"], index=0)
        tracking_type_dict = {"Fiksni položaj modula": 0, "Horizontalna os S-J": 1, "Dvoosni": 2, "Vertikalna os": 3, "Horizontalno I-Z": 4}
        
    #Advanced system parameters (collapsible)
    #with st.expander("Napredni parametri sustava"):
        #col1, col2 = st.columns(1) if st.session_state.get('_is_mobile', False) else st.columns(2)
        #with col1:
            #dc_ac_ratio = st.number_input("DC/AC omjer", min_value=1.0, max_value=2.0, value=1.2, step=0.05)
            #inverter_efficiency = st.slider("Efikasnost invertera (%)", min_value=90, max_value=99, value=96, step=1)
        #with col2:
            #temperature_coefficient = st.number_input("Temperaturni koeficijent gubitaka modula (%/°C)", min_value=-0.5, max_value=0.0, value=-0.4, step=0.01)
            #degradation_rate = st.slider("Godišnja stopa degradacije modula (%)", min_value=0.0, max_value=2.0, value=0.8, step=0.1) 

                   
             
with tabs[1]:
    st.header("Proizvodnja energije solarne elektrane")
    st.write("Procijenjena proizvodnja električne energije solarne elektrane prema lokaciji i parametrima sustava.")
    
    tmy_data, meta = get_pvgis_tmy(latitude, longitude)
    tmy_data = tmy_data.tz_convert(timezone)

    def calculate_solar_production(latitude, longitude, altitude, timezone, 
                                  system_capacity_kw, module_type, total_system_losses_percent, 
                                  tilt, azimuth, tracking, 
                                  dc_ac_ratio, temperature_coefficient, tmy_data,inverter_efficiency):
        # Create location object
        site = Location(latitude, longitude, timezone, altitude, f'Solar Site at {latitude:.4f}, {longitude:.4f}')
        
        # Define time period for simulation (1 year with hourly resolution)
        start = pd.Timestamp(datetime.now().year, 1, 1, 0, 0, 0, tz=timezone)
        end = pd.Timestamp(datetime.now().year, 12, 31, 23, 0, 0, tz=timezone)
        time_range = pd.date_range(start=start, end=end, freq='1h', tz=timezone)

        tmy_data.index=time_range       
   
        # Set up PV system parameters
        module_parameters = {
            'pdc0': system_capacity_kw * 1000,  # Convert kW to W
            'gamma_pdc': temperature_coefficient / 100,  # Convert from %/C to 1/C
        }
        
        # Critical: Define inverter max AC output based on DC/AC ratio
        paco = (system_capacity_kw * 1000) / dc_ac_ratio  # Max AC power in Watts
        
        # Set up temperature model parameters based on module type
        temp_model = TEMPERATURE_MODEL_PARAMETERS['sapm']['open_rack_glass_glass']
        
        # Create PV system object
        # Add inverter parameters to fix the error
        inverter_parameters = {
        'pdc0': system_capacity_kw * 1000,  # Often same as module pdc0
        'paco': paco,
        'eta_inv_nom': inverter_efficiency/100,  # Convert from % to decimal
        }
        
        if tracking == "Fiksni položaj modula":  
            system = PVSystem(
                surface_tilt=tilt,
                surface_azimuth=azimuth,
                module_parameters=module_parameters,
                temperature_model_parameters=temp_model,
                losses_parameters={'dc_ohmic_percent': total_system_losses_percent},
                inverter_parameters=inverter_parameters
            )
        elif tracking == "Jednoosni":
            system = PVSystem(
                surface_tilt=tilt,
                surface_azimuth=azimuth,
                module_parameters=module_parameters,
                temperature_model_parameters=temp_model,
                losses_parameters={'dc_ohmic_percent': total_system_losses_percent},
                inverter_parameters=inverter_parameters,
                tracking_parameters={'axis_tilt': 0, 'axis_azimuth': 180, 'max_angle': 90, 'backtrack': True}
            )
        else:  # Dual-Axis
            system = PVSystem(
                surface_tilt=0,  # Will be adjusted dynamically
                surface_azimuth=180,  # Will be adjusted dynamically
                module_parameters=module_parameters,
                temperature_model_parameters=temp_model,
                losses_parameters={'dc_ohmic_percent': total_system_losses_percent},
                inverter_parameters=inverter_parameters
            )
        
        # Create ModelChain object
        mc = ModelChain(system, site, aoi_model='physical', spectral_model='no_loss',losses_model='no_loss')
        
        # Run the simulation with TMY data
        #weather = site.get_clearsky(time_range)
        weather = tmy_data[['ghi', 'dni', 'dhi', 'temp_air', 'wind_speed']].copy()      
        
        # Run the model
        mc.run_model(weather)

        #ac_power_w = mc.results.ac * (1 - total_system_losses_percent / 100)   
        ac_power_w = mc.results.ac     
        # Convert to DataFrame with datetime index
        df = pd.DataFrame({
            'ac_power_w': ac_power_w,
            'ac_power_kw': ac_power_w / 1000,  # Convert W to kW
            'ghi': weather['ghi'],
            'dni': weather['dni'],
            'dhi': weather['dhi'],
        }, index=time_range)
        
        return df
    def get_hourly_radiation(latitude, longitude, start_year=2019, end_year=2019, peakpower=system_capacity_kw, loss=14, angle=20, aspect=0, pvtechchoice='crystSi', mountingplace='free', trackingtype=0):
        """
        Fetch hourly solar radiation data from PVGIS API.
        
        Parameters:
        - lat (float): Latitude of the location.
        - lon (float): Longitude of the location.
        - start_year (int): Starting year for data (optional, defaults to 2005).
        - end_year (int): Ending year for data (optional, defaults to 2020).
        
        Returns:
        - pd.DataFrame: DataFrame with hourly radiation data.
        """
        base_url = "https://re.jrc.ec.europa.eu/api/v5_2/seriescalc"
        
        params = {
            "lat": latitude,
            "lon": longitude,
            "startyear": start_year,
            "endyear": end_year,
            "peakpower": peakpower,
            "loss": loss,
            "angle": angle,
            "aspect": aspect,
            "pvtechchoice": pvtechchoice,  # Crystalline Silicon
            "mountingplace": mountingplace,  # Free-standing
            "trackingtype": trackingtype,          # 0 = fixed
            "optimalinclination": 0,  # 0 = use specified angle
            "optimalangles" : 0,      # 0 = use specified aspect
            "pvcalculation": 1,  # 0 = only radiation, 1 = include PV production
            "components": 0,     # 1 = include beam/diffuse/reflected components
            "outputformat": "json",
            "browser": 0         # 0 = stream response
        }
        
        response = requests.get(base_url, params=params)
        
        if response.status_code != 200:
            raise Exception(f"API request failed: {response.status_code} - {response.text}")
        
        data = response.json()

        #start = pd.Timestamp(datetime.now().year, 1, 1, 0, 0, 0, tz=timezone)
        #end = pd.Timestamp(datetime.now().year, 12, 31, 23, 0, 0, tz=timezone)
        #time_range = pd.date_range(start=start, end=end, freq='1h', tz=timezone)
        
        # Extract the hourly data from the JSON response
        hourly_list = data.get("outputs", {}).get("hourly", [])
        
        if not hourly_list:
            raise Exception("No hourly data found in the response.")
        
        # Convert to pandas DataFrame
        df = pd.DataFrame(hourly_list)
        
        # Parse the 'time' column to datetime if present
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'], format='%Y%m%d:%H%M')
        df.set_index('time', inplace=True)
        return df

    
    # Calculate production if user clicks the button
    if st.button("Izračunaj proizvodnju SE"):
        with st.spinner("Računam proizvodnju SE..."):
            try:
                # Get production data            
     
                production_data = get_hourly_radiation(latitude, longitude, start_year=2019, end_year=2019, peakpower=system_capacity_kw, 
                                                       loss=total_system_losses_percent,pvtechchoice=module_type, angle=tilt, aspect=azimuth,
                                                       trackingtype=tracking_type_dict[tracking_type])
                production_data['ac_power_kw'] = production_data['P']  / 1000  # Convert W to kW
                # Store the data in session state for use in other tabs
                st.session_state['production_data'] = production_data
                
                # Display summary statistics
                total_annual_kwh = production_data['ac_power_kw'].sum()
                avg_daily_kwh = total_annual_kwh / 365
                peak_power_kw = production_data['ac_power_kw'].max()
                capacity_factor = (total_annual_kwh / (system_capacity_kw * 8760)) * 100
                specific_yield = total_annual_kwh / system_capacity_kw
                #production_data.to_csv('Production_data.csv')
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Ukupna godišnja proizvodnja", f"{total_annual_kwh:.2f} kWh")
                col2.metric("Specifična proizvodnja", f"{specific_yield:.2f} kWh/kW") 
                col2.metric("Faktor angažiranja solarne elektrane ", f"{capacity_factor:.2f} %")
                col3.metric("Prosječna dnevna proizvodnja", f"{avg_daily_kwh:.2f} kWh")
                col3.metric("Zabilježena vršna snaga", f"{peak_power_kw:.2f} kW")   
                

                st.write("Za detaljan prikaz podataka o proizvodnji i potrošnji energije ispunite potrebne podatke u kartici 'Potrošnja' ")               
                           
            except Exception as e:
                st.error(f"Greška pri izračunu proizvodnje SE: {str(e)}")
                st.error("Molim vas pregledajte ulazne parametre i pokušajte ponovno.")
    else:
        st.info("Kliknite na  'Izračunaj proizvodnju SE' kako bi generirali procjenu proizvodnje SE")

with tabs[2]:   
    st.header("Potrošnja električne energije kućanstva")
    st.write("Profil potrošnje energije; moguće je odabrati predefinirani profili ili unijeti vlastite podatke o potrošnji električne energije")

    # Mode selector (radio buttons) to choose input method
    input_mode = st.radio(
        "Odaberite način unosa potrošnje:",
        options=["Predefinirani profil", "Uploadirajte satne podatke"],
        index=0,  # Default to predefined
        key='input_mode_cons',
        help="Predefinirani: unaprijed određeni profil ; Upload za podatke o vlastitoj potrošnji. Prebacivanje briše prethodne podatke"
    )

    if input_mode == "Predefinirani profil":
        # Clear any upload state when switching to predefined
        if 'consumption_file' in st.session_state:
            del st.session_state['consumption_file']
            st.rerun()  # Safe here, as it's in main script
            st.success("Uploadirana datoteka uklonjena. Koristi se predefinirani profil.")
        
        st.info("Koristi se predefinirani profil potrošnje.")
        
        # Predefined inputs
        annual_consumption = st.number_input("Godišnja potrošnja električne energije (kWh)", min_value=1000.0, max_value=100000.0, value=5595.4, step=100.0, key='annual_consumption')
        
        # Consumption pattern options
        consumption_pattern = st.selectbox(
            "Uzorak potrošnje energije", 
            options=["Jednoliko distribuirana", "Veća potrošnja tijekom dana", "Veća potrošnja tijekom večeri", "Sezonska (veća potrošnja ljeti)", "Sezonska (veća potrošnja zimi)"],
            index=0,
            key='consumption_pattern'
        )
        
    elif input_mode == "Uploadirajte satne podatke":
        # Clear any predefined changes? Not needed, as we use upload exclusively here
        
        st.write("Uploadirajte svoju satnu potrošnju električne energije u CSV ili Excel formatu.")        
        st.write("Datoteka treba sadržavati vrijednosti satne potrošnje u kW ili kWh za cijelu godinu (8760 sati).")
        
        # File format explanation
        with st.expander("Format datoteke treba ispunjavati uvjete:"):
            st.markdown("""
            ### Potrebni format datotekje:
            - CSV ili Excel datoteka sa podacima o satnoj potrošnji
            - Datoteka treba sadržavati 8760 podataka (jedna puna godina satnih iznosa potrošnje)
            - Podaci trebaju biti unešeni u jedan stupac bez naslova
            - Vrijednosti potrošnje trebaju biti u kW ili kWh
            
            ### Primjer:
            ```
            0.5
            0.7
            0.6
            ...
            ```
            
            ### Izborne opcije:
            - Ako datoteka sadrži stupac sa datumom i vremenom, možete specificirati koji stupac sadrži vrijednosti potrošnje        
            - Ako datoteka sadrži manje od 8760 podataka o potrošnji, podaci će se ponavljati dok se ne popuni čitava godina
            """)
        
        # File uploader
        uploaded_file = st.file_uploader("Izaberite datoteku", type=["csv", "xlsx", "xls"], key='consumption_file')
        
        # Manual clear button (for removing file without mode switch)
        if uploaded_file is not None:
            if st.button("Ukloni uploadiranu datoteku"):
                if 'consumption_file' in st.session_state:
                    del st.session_state['consumption_file']
                st.rerun()
                st.info("Datoteka uklonjena. Prebacite se na predefinirani profil za automatsko ažuriranje.")
        
        # Options for file processing (only show if file uploaded)
        if uploaded_file is not None:
            st.success("Datoteka uspješno uploadirana!")
            
            # File processing options
            col1, col2 = st.columns(2)
            with col1:
                skip_rows = st.number_input("Preskoči redaka", min_value=0, value=0, help="Broj redaka naslova za preskočiti", key='skip_rows_cons')
                has_header = st.checkbox("Datoteka sadrži naslov stupca", value=False, key='has_header_cons')
            
            with col2:
                if has_header:
                    column_name = st.text_input("Stupac sa podacima o potrošnji", value="potrošnja", 
                                                help="Naslov stupca koji sadrži podatke o potrošnji", key='column_name_cons')
                else:
                    column_index = st.number_input("Broj stupca sa podacima o potrošnji", min_value=0, value=0,
                                                help="Index stupca koji sadrži podatke o potrošnji (0 za prvi stupac)", key='column_index_cons')
            
            # Preview uploaded data
            st.write("Pregled uploadiranih podataka:")
            try:
                uploaded_file.seek(0)  # Reset position for preview
                if uploaded_file.name.endswith('.csv'):
                    preview_df = pd.read_csv(uploaded_file, nrows=5, decimal='.')
                else:  # Excel file
                    preview_df = pd.read_excel(uploaded_file, nrows=5)
                
                st.dataframe(preview_df)
                uploaded_file.seek(0)  # Reset for future reads
                
            except Exception as e:
                st.error(f"Greška kod pregleda datoteke: {str(e)}")
                st.error("Molimo provjerite format datoteke i pokušajte ponovno.")

    # Reactive computation (runs on every rerun if production data exists)
    if 'production_data' not in st.session_state:
        st.warning("Molim izračunajte proizvodnju SE u kartici Proizvodnja.")
        st.session_state['consumption_data'] = None
    else:
        input_mode = st.session_state.get('input_mode_cons', 'Predefinirani profil')  # Get from session state
        uploaded_file = None if input_mode == "Predefinirani profil" else st.session_state.get('consumption_file')
        use_predefined_pattern = (input_mode == "Predefinirani profil" or uploaded_file is None)
  
    if 'production_data' in st.session_state and st.session_state['consumption_data'] is None:
        with st.spinner("Računam potrošnju..."):
            try:
                # Get production data from session state
                prod_copy = st.session_state['production_data'].copy()
                
                # Generate hourly consumption profile based on input method
                hours_in_year = 8760
                hourly_consumption = np.zeros(hours_in_year)
                
                # Check if user uploaded consumption data (current state)
                uploaded_file = st.session_state.get('consumption_file')
                use_predefined_pattern = uploaded_file is None
                
                if not use_predefined_pattern:
                    try:
                        # Get file processing params from session state (via keys)
                        skip_rows = st.session_state.get('skip_rows_cons', 0)
                        has_header = st.session_state.get('has_header_cons', False)
                        column_name = st.session_state.get('column_name_cons', 'potrošnja') if has_header else None
                        column_index = st.session_state.get('column_index_cons', 0) if not has_header else None
                        
                        # Reset file position and read the file
                        uploaded_file.seek(0)
                        if uploaded_file.name.endswith('.csv'):
                            if has_header:
                                consumption_df_raw = pd.read_csv(uploaded_file, skiprows=skip_rows, decimal='.')
                                consumption_values = consumption_df_raw[column_name].values
                            else:
                                consumption_df_raw = pd.read_csv(uploaded_file, header=None, skiprows=skip_rows, decimal='.')
                                consumption_values = consumption_df_raw.iloc[:, column_index].values
                        else:  # Excel file
                            if has_header:
                                consumption_df_raw = pd.read_excel(uploaded_file, skiprows=skip_rows)
                                consumption_values = consumption_df_raw[column_name].values
                            else:
                                consumption_df_raw = pd.read_excel(uploaded_file, header=None, skiprows=skip_rows)
                                consumption_values = consumption_df_raw.iloc[:, column_index].values
                        
                        # Handle case where uploaded data doesn't have exactly 8760 values
                        if len(consumption_values) < hours_in_year:
                            # Repeat the data to fill a full year
                            repetitions = int(np.ceil(hours_in_year / len(consumption_values)))
                            consumption_values = np.tile(consumption_values, repetitions)[:hours_in_year]
                            st.info(f"Uploaded data had {len(consumption_values)} values, repeated to fill 8760 hours.")
                        elif len(consumption_values) > hours_in_year:
                            # Truncate to 8760 values
                            consumption_values = consumption_values[:hours_in_year]
                            st.info(f"Uploaded data had more than 8760 values, truncated to first 8760 hours.")
                        
                        # Use the uploaded consumption values
                        hourly_consumption = consumption_values
                        
                        # Calculate actual annual consumption from uploaded data
                        actual_annual_consumption = hourly_consumption.sum()
                        
                    except Exception as e:
                        st.error(f"Greška u obradi uploadiranih podataka o potrošnji: {str(e)}")
                        st.error("Korišten je predefinirani uzorak potrošnje.")
                        use_predefined_pattern = True
                else:
                    # No uploaded file, use predefined patterns
                    annual_consumption = st.session_state.get('annual_consumption', 5595.4)
                    consumption_pattern = st.session_state.get('consumption_pattern', 'Jednoliko distribuirana')
                
                # Use predefined patterns if no upload or if there was an error
                if use_predefined_pattern:
                    if consumption_pattern == "Jednoliko distribuirana":
                        hourly_consumption = np.ones(hours_in_year) * (annual_consumption / hours_in_year)
                    
                    elif consumption_pattern == "Veća potrošnja tijekom dana":
                        # More consumption during daytime (8am-6pm)
                        for i in range(hours_in_year):
                            hour = i % 24
                            if 8 <= hour < 18:  # Daytime hours
                                hourly_consumption[i] = 1.5
                            else:
                                hourly_consumption[i] = 0.5
                        # Normalize to match annual consumption
                        hourly_consumption = hourly_consumption * (annual_consumption / hourly_consumption.sum())
                    
                    elif consumption_pattern == "Veća potrošnja tijekom večeri":
                        # More consumption during evening (5pm-11pm)
                        for i in range(hours_in_year):
                            hour = i % 24
                            if 17 <= hour < 23:  # Evening hours
                                hourly_consumption[i] = 2.0
                            else:
                                hourly_consumption[i] = 0.5
                        # Normalize to match annual consumption
                        hourly_consumption = hourly_consumption * (annual_consumption / hourly_consumption.sum())
                    
                    elif consumption_pattern == "Sezonska (veća potrošnja ljeti)":
                        # More consumption in summer months (May-Sep)
                        for i in range(hours_in_year):
                            month = prod_copy.index[i].month
                            if 5 <= month <= 9:  # Summer months
                                hourly_consumption[i] = 1.5
                            else:
                                hourly_consumption[i] = 0.5
                        # Normalize to match annual consumption
                        hourly_consumption = hourly_consumption * (annual_consumption / hourly_consumption.sum())
                    
                    elif consumption_pattern == "Sezonska (veća potrošnja zimi)":
                        # More consumption in winter months (Nov-Mar)
                        for i in range(hours_in_year):
                            month = prod_copy.index[i].month
                            if month <= 3 or month >= 11:  # Winter months
                                hourly_consumption[i] = 1.5
                            else:
                                hourly_consumption[i] = 0.5
                        # Normalize to match annual consumption
                        hourly_consumption = hourly_consumption * (annual_consumption / hourly_consumption.sum())
                
                # Create DataFrame with consumption data
                consumption_df = pd.DataFrame({
                    'consumption_kw': hourly_consumption
                }, index=prod_copy.index)
                
                # Store actual annual consumption for reporting
                actual_annual_consumption = consumption_df['consumption_kw'].sum()
                
                # Combine production and consumption data
                energy_balance = pd.DataFrame({
                    'production_kw': prod_copy['ac_power_kw'],
                    'consumption_kw': consumption_df['consumption_kw']
                })
                
                # Calculate net energy (positive = excess, negative = deficit)
                energy_balance['net_kw'] = energy_balance['production_kw'] - energy_balance['consumption_kw']
                
                # Calculate self-consumption and grid export/import
                energy_balance['self_consumed_kw'] = np.minimum(energy_balance['production_kw'], energy_balance['consumption_kw'])
                energy_balance['exported_kw'] = np.maximum(0, energy_balance['net_kw'])
                energy_balance['imported_kw'] = np.maximum(0, -energy_balance['net_kw'])
                
                # Pre-calculate metrics for display
                total_annual_load_kWh = consumption_df['consumption_kw'].sum()
                avg_daily_load_kwh = total_annual_load_kWh / 365
                peak_power_load_kw = consumption_df['consumption_kw'].max()
                
                total_annual_kwh = prod_copy['ac_power_kw'].sum()
                avg_daily_kwh = total_annual_kwh / 365
                peak_power_kw = prod_copy['ac_power_kw'].max()
                
                # Store computed data in session state for display (overwrites on each update)
                st.session_state['consumption_data'] = {
                    'consumption_df': consumption_df,
                    'energy_balance': energy_balance,
                    'total_annual_load_kWh': total_annual_load_kWh,
                    'avg_daily_load_kwh': avg_daily_load_kwh,
                    'peak_power_load_kw': peak_power_load_kw,
                    'total_annual_kwh': total_annual_kwh,
                    'avg_daily_kwh': avg_daily_kwh,
                    'peak_power_kw': peak_power_kw
                }
                
                st.success("Podaci o potrošnji ažurirani!")

                #consumption_df.to_csv('consumption_df.csv')
                
            except Exception as e:
                st.error(f"Greška pri obradi podataka: {str(e)}")
                st.error("Molim pregledajte ulazne podatke i pokušajte ponovno.")
                st.session_state['consumption_data'] = None



    # Display section (renders if computed data exists, updates reactively)
    if st.session_state.get('consumption_data') is not None:
        data = st.session_state['consumption_data']
        #production_data = st.session_state['production_data']        
        consumption_df=st.session_state['consumption_data']['consumption_df']
        def calculate_self_consumption_metrics(production_df, consumption_df):
            # Align indices (both should be 8760 hourly)
            common_index = production_df.index.intersection(consumption_df.index)
            pv_hourly = production_df.loc[common_index, 'ac_power_kw'].fillna(0)
            load_hourly = consumption_df.loc[common_index, 'consumption_kw'].fillna(0)
            
            # Self-consumed = min(PV, load) for each hour
            self_consumed_hourly = np.minimum(pv_hourly, load_hourly)
            
            # Annual totals
            annual_pv = pv_hourly.sum()
            annual_load = load_hourly.sum()
            annual_self_consumed = self_consumed_hourly.sum()
            
            # Ratios (avoid division by zero)
            self_consumption_ratio = (annual_self_consumed / annual_pv * 100) if annual_pv > 0 else 0
            self_sufficiency_ratio = (annual_self_consumed / annual_load * 100) if annual_load > 0 else 0
            
            return {
                'annual_pv_kwh': annual_pv,
                'annual_load_kwh': annual_load,
                'annual_self_consumed_kwh': annual_self_consumed,
                'self_consumption_pct': round(self_consumption_ratio, 1),
                'self_sufficiency_pct': round(self_sufficiency_ratio, 1)
            }

        metrics = calculate_self_consumption_metrics( prod_copy, consumption_df)
        
        
        # Display summary statistics
        col1, col2, col3 = st.columns(3)
        col1.metric("Ukupna godišnja potrošnja", f"{data['total_annual_load_kWh']:.2f} kWh")
        col2.metric("Prosječna dnevna potrošnja", f"{data['avg_daily_load_kwh']:.2f} kWh")
        col3.metric("Zabilježena vršna potrošnja", f"{data['peak_power_load_kw']:.2f} kW")
        
        col1.metric("Ukupna godišnja proizvodnja", f"{data['total_annual_kwh']:.2f} kWh")
        col2.metric("Prosječna dnevna proizvodnja", f"{data['avg_daily_kwh']:.2f} kWh")
        col3.metric("Zabilježena vršna proizvodnja", f"{data['peak_power_kw']:.2f} kW")    

        col1.metric("Stopa samopotrošnje", f"{metrics['self_consumption_pct']}%")
        
        # Create monthly production chart
        monthly_production = prod_copy.resample('ME')['ac_power_kw'].sum()
        monthly_production.index = monthly_production.index.strftime('%b')
        monthly_load = data['consumption_df'].resample('ME')['consumption_kw'].sum()
        monthly_load.index = monthly_load.index.strftime('%b')
        
        # Combine into a DataFrame
        df_combined = pd.DataFrame({
            'Mjesec': monthly_production.index,
            'Proizvodnja': monthly_production.values,
            'Potrošnja': monthly_load.values
        })

        # Melt to long format for grouped bars
        df_long = df_combined.melt(id_vars='Mjesec', value_vars=['Proizvodnja', 'Potrošnja'],
                                var_name='Vrsta', value_name='Energija (kWh)')

        # Create grouped bar chart
        fig = px.bar(
            df_long,
            x='Mjesec',
            y='Energija (kWh)',
            color='Vrsta',
            barmode='group',  # Side-by-side bars
            labels={'Mjesec': 'Mjesec', 'Energija (kWh)': 'Energija (kWh)'},
            title='Mjesečna proizvodnja i potrošnja energije',
            color_discrete_sequence=['#FFA500', '#1f77b4']  # Orange for production, blue for load
        )
        fig.update_layout(
            autosize=True,
            margin=dict(l=10, r=10, t=30, b=10),
            height=350 if st.session_state.get('_is_mobile', False) else 500
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Create hourly heatmap for daily consumption patterns
        hourly_data = data['consumption_df'].copy()
        hourly_data['hour'] = data['consumption_df'].index.hour
        hourly_data['month'] = data['consumption_df'].index.month
        
        # Pivot the data to create a month vs hour heatmap
        pivot_data = hourly_data.pivot_table(
            index='hour', 
            columns='month', 
            values='consumption_kw', 
            aggfunc='mean'
        )
        
        # Create heatmap
        fig = px.imshow(
            pivot_data,
            labels=dict(x="Mjesec", y="Sat u danu", color="Prosječna snaga (kW)"),
            x=[f"{m}" for m in range(1, 13)],
            y=[f"{h}:00" for h in range(24)],
            color_continuous_scale='YlOrRd',
            title="Prosječna satna potrošnja po mjesecima"
        )
        fig.update_layout(
            autosize=True,
            margin=dict(l=10, r=10, t=30, b=10),
            height=350 if st.session_state.get('_is_mobile', False) else 500
        )
        st.plotly_chart(fig, use_container_width=True)

        # Create hourly heatmap for daily production patterns
        hourly_data = prod_copy.copy()
        hourly_data['hour'] = prod_copy.index.hour
        hourly_data['month'] = prod_copy.index.month
        
        # Pivot the data to create a month vs hour heatmap
        pivot_data = hourly_data.pivot_table(
            index='hour', 
            columns='month', 
            values='ac_power_kw', 
            aggfunc='mean'
        )
        
        # Create heatmap
        fig = px.imshow(
            pivot_data,
            labels=dict(x="Mjesec", y="Sat u danu", color="Prosječna snaga (kW)"),
            x=[f"{m}" for m in range(1, 13)],
            y=[f"{h}:00" for h in range(24)],
            color_continuous_scale='YlOrRd',
            title="Prosječna satna proizvodnja po mjesecima"
        )
        fig.update_layout(
            autosize=True,
            margin=dict(l=10, r=10, t=30, b=10),
            height=350 if st.session_state.get('_is_mobile', False) else 500
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Show daily production for a sample month
        st.subheader("Dnevni profil proizvodnje i potrošnje")
        sample_month = st.selectbox("Odaberite mjesec za prikaz dnevnog profila:", 
                                    options=range(1, 13), 
                                    format_func=lambda x: datetime(2000, x, 1).strftime('%B'),
                                    index=6, key='sample_month_cons')  # Default to July, with key for state
        
        # Filter data for selected month
        month_data = prod_copy[prod_copy.index.month == sample_month]
        month_load_data = data['consumption_df'][data['consumption_df'].index.month == sample_month]
        
        # Group by hour of day
        hourly_avg = month_data.groupby(month_data.index.hour)['ac_power_kw'].mean()
        hourly_avg_load = month_load_data.groupby(month_load_data.index.hour)['consumption_kw'].mean()
        
        # Combine into a DataFrame (index is hours)
        df_comb = pd.DataFrame({
            'Proizvodnja': hourly_avg,
            'Potrošnja': hourly_avg_load
        })
        
        # Create line chart with both lines
        fig = px.line(
            df_comb,
            y=['Proizvodnja', 'Potrošnja'],  # Plot multiple y columns
            labels={'index': 'Sat', 'value': 'Prosječna snaga (kW)'},
            title=f'Prosječni dnevni profil proizvodnje i potrošnje za {datetime(2000, sample_month, 1).strftime("%B")}',
            markers=True,
            color_discrete_sequence=['#FFA500', '#1f77b4']  # Orange for production, blue for consumption
        )     
        fig.update_layout(xaxis=dict(tickmode='linear', tick0=0, dtick=2))
        st.plotly_chart(fig, use_container_width=True)     
        
    else:
        st.info("Kliknite na karticu Proizvodnja da biste izračunali proizvodnju, zatim izmijenite podatke o potrošnji za automatsko ažuriranje.")


with tabs[3]:
    st.header("Godišnji račun")
    st.write("Izračun godišnjeg troška za električnu energiju")
    
    # Financial inputs section
    st.subheader("Parametri")
    col1, col2 = st.columns(1) if st.session_state.get('_is_mobile', False) else st.columns(2)

    with col1:
        # Electricity rates
         tariff = st.selectbox("Tarifni model", options=[ "Bijeli (VT_NT)","Plavi (JT)", "Crveni (VT_NT)", "Crni (JT)" ], index=0)
         
    if st.button("Izračunaj godišnji trošak za električnu energiju"):

        with st.spinner("Računam godišnji trošak za električnu energiju..."):

            production_data = st.session_state['production_data']
            consumption_df=st.session_state['consumption_data']['consumption_df']
            no_pv_df=production_data.copy()
            no_pv_df['ac_power_kw']=0
            prices_csv=f'{tariff}.csv'
            prices_df=pd.read_csv(prices_csv,index_col=None) 
            
            st.session_state['prices_df']=prices_df

            obracun_energije_month, racuni_month, bilanca_month, godišnji_month = izvrši_obracun(production_data,consumption_df,prices_df,net_interval='month')
            obracun_energije_15min, racuni_15min, bilanca_15min,godišnji_15min = izvrši_obracun(production_data,consumption_df,prices_df,net_interval='15min')
            obracun_energije_noPV, racuni_noPV, bilanca_noPV,godišnji_noPV = izvrši_obracun(no_pv_df,consumption_df,prices_df)

            st.session_state['racuni_month']=racuni_month
            st.session_state['racuni_15min']=racuni_15min   
            st.session_state['racuni_noPV']=racuni_noPV

            month_names = ['Siječanj', 'Veljača', 'Ožujak', 'Travanj', 'Svibanj', 'Lipanj',
                        'Srpanj', 'Kolovoz', 'Rujan', 'Listopad', 'Studeni', 'Prosinac']
            
            bills_month = [racuni_month[month].loc[9, 'Iznos EUR'] for month in month_names]
            bills_15min = [racuni_15min[month].loc[9, 'Iznos EUR'] for month in month_names]
            bills_noPV = [racuni_noPV[month].loc[9, 'Iznos EUR'] for month in month_names]

            total_month = bilanca_month.loc['Year', 'Bill']
            total_15min = bilanca_15min.loc['Year', 'Bill']
            total_noPV = bilanca_noPV.loc['Year', 'Bill']

            col1, col2, col3 = st.columns(3)
            col1.metric("Ukupan godišnji trošak - mjesečno netiranje", f"{total_month:.2f} EUR")
            col2.metric("15min netiranje", f"{total_15min:.2f} EUR")
            col3.metric("Bez solarne elektrane", f"{total_noPV:.2f} EUR") 

            st.download_button("Preuzmi godišnji račun (CSV)", godišnji_month.to_csv(), "godisnji_racun.csv")          
      

            # Combine into a DataFrame 
            df_3 = pd.DataFrame({
                'Mjesec': month_names,
                'Bez SE': bills_noPV, 
                'Mjesečno netiranje': bills_month, 
                '15min netiranje': bills_15min,                            
            })
                           
            # Melt to long format for grouped bars
            df_long = df_3.melt(id_vars='Mjesec', value_vars=['Bez SE','Mjesečno netiranje', '15min netiranje'],
                                    var_name='Vrsta', value_name='EUR')

            # Create grouped bar chart
            fig = px.bar(
                df_long,
                x='Mjesec',
                y='EUR',
                color='Vrsta',
                barmode='group',  # Side-by-side bars
                labels={'Mjesec': 'Mjesec', 'Energija (kWh)': 'Energija (kWh)'},
                title='Iznos mjesečnih računa za električnu energiju',
                color_discrete_sequence=["#a3a3a3", "#ffea30","#f79729"]  # Colors
            )
            fig.update_layout(
                autosize=True,
                margin=dict(l=10, r=10, t=30, b=10),
                height=350 if st.session_state.get('_is_mobile', False) else 500
            )
            st.plotly_chart(fig, use_container_width=True)   
                  
            fig_bill = plot_bill_style_plotly(godišnji_month[godišnji_month.index<10])
            #st.plotly_chart(fig_bill, use_container_width=True)
            
            fig_bill2 = plot_bill_style_plotly(godišnji_15min[godišnji_15min.index<10])

            #fig_bill_matplot = plot_bill_style(godišnji_month[godišnji_month.index<10])
            #st.pyplot(fig_bill_matplot) 
        col1, col2 = st.columns([1, 1])
        with col1: 
            st.write("Godišnji račun - mjesečno netiranje")
            display_bill_table(fig_bill,godišnji_month[godišnji_month.index<10])

        with col2: 
            st.write("Godišnji račun - 15min netiranje")
            display_bill_table(fig_bill2,godišnji_month[godišnji_month.index<10])
    
    if st.button("Prikaži mjesečne račune za električnu energiju"):  
        racuni_month=st.session_state['racuni_month']
        racuni_15min=st.session_state['racuni_15min']
       

        with st.spinner("Pripremam mjesečne račune ..."):
            col1, col2 = st.columns([1, 1])
            month_names = ['Siječanj', 'Veljača', 'Ožujak', 'Travanj', 'Svibanj', 'Lipanj',
               'Srpanj', 'Kolovoz', 'Rujan', 'Listopad', 'Studeni', 'Prosinac']
            with col1:
                for month in month_names:
                    st.markdown(f"""
                        <div style='text-align: center; font-size:20; font-family: Arial; font-weight: bold; color: blue;'>
                        {month}
                        </div>
                        """, unsafe_allow_html=True)
                    #st.markdown("<br>", unsafe_allow_html=True) 
                    racun=racuni_month[month]
                    fig1 = plot_bill_style(racun[racun.index<10])
                    fig2 = plot_bill_style2(racun[(racun.index > 10) & (racun.index < 16)])
                    fig3 = plot_bill_style3(racun[racun.index>15])
                    st.pyplot(fig1)
                    st.pyplot(fig2)
                    st.pyplot(fig3)

            with col2:
                for month in month_names:
                    st.markdown(f"""
                        <div style='text-align: center; font-size:20; font-family: Arial; font-weight: bold; color: blue;'>
                        {month}
                        </div>
                        """, unsafe_allow_html=True)
                    #st.markdown("<br>", unsafe_allow_html=True) 
                    racun=racuni_15min[month]
                    fig1 = plot_bill_style(racun[racun.index<10])
                    fig2 = plot_bill_style2(racun[(racun.index > 10) & (racun.index < 16)])
                    fig3 = plot_bill_style3(racun[racun.index>15])
                    st.pyplot(fig1)
                    st.pyplot(fig2)
                    st.pyplot(fig3) 

with tabs[4]:
    st.header("Financijska analiza")
    st.write("Analiza isplativosti ulaganja u solarnu elektranu kod mjesečno i 15minutnog netiranja energije")

    # Financial inputs section
    st.subheader("Financijski parametri")
    col1, col2 = st.columns(1) if st.session_state.get('_is_mobile', False) else st.columns(2)
    
    with col1:       
        system_cost_per_kw = st.number_input("Trošak izgradnje solarne elektrane (€/kW)", min_value=500, max_value=5000, value=1000, step=10) 
        system_cost_per_watt = system_cost_per_kw / 1000  # Convert to €/W
        
        incentive_percent = st.slider("Dobiveni poticaji (% od ukupnog troška)", min_value=0, max_value=100, value=0, step=5) 
        loan_percent = st.slider("Postotak financiranja putem kredita (%)", min_value=0, max_value=100, value=0, step=5)
        loan_interest_rate = st.slider("Kamatna stopa kredita (%)", min_value=0.0, max_value=10.0, value=3.0, step=0.1)
        loan_term_years = st.slider("Rok otplate kredita (godine)", min_value=1, max_value=25, value=10, step=1)
        discount_rate = st.slider("Diskontna stopa (%)", min_value=0.0, max_value=10.0, value=4.0, step=0.1)
        
    with col2:   
        inverter_replacement_cost = st.number_input("Trošak zamjene invertera (€)", min_value=100.0, max_value=5000.0, value=500.0, step=10.0)
        system_lifetime_years = st.slider("Vijek trajanja sustava (godine)", min_value=10, max_value=25, value=25, step=1)
        degradation_rate = st.slider("Godišnja stopa degradacije panela (%)", min_value=0.0, max_value=5.0, value=0.8, step=0.1)      
        maintenance_cost_percent = st.slider("Troškovi održavanja i osiguranja (% troška izgradnje SE)", min_value=0.0, max_value=5.0, value=0.5, step=0.1)               
        annual_rate_increase = st.slider("Godišnja stopa rasta cijene el. energije (%)", min_value=0.0, max_value=10.0, value=2.0, step=0.5)
        inflation_rate = st.slider("Godišnja stopa inflacije (%)", min_value=0.0, max_value=10.0, value=2.0, step=0.5)
    
    
    if st.button("Izvrši financijsku analizu"):

        start_time = time.time()

        # Placeholders for live timer and final message     
        timer_placeholder = st.empty()
        spinner_placeholder = st.spinner("Vršim financijsku analizu...")      

        st.write("Vrijeme izvođenja analize može varirati ovisno o performansama računala (oko 60 sekundi)")
        if 'production_data' not in st.session_state or 'prices_df' not in st.session_state:     
            st.warning("Molim izračunajte proizvodnju SE u kartici Proizvodnja i Godišnji račun...")
        else:
            with spinner_placeholder:          
                    # Get production data from session state
                    production_data = st.session_state['production_data']
                    no_pv_df=production_data.copy()
                    no_pv_df['ac_power_kw']=0
                    prices_df=st.session_state['prices_df']                    
                    consumption_df=st.session_state['consumption_data']['consumption_df']

                    def calculate_loan_payment(principal, annual_rate, years):
                        """Calculate annual loan payment using annuity formula"""
                        if annual_rate == 0 or years == 0:
                            return principal / years if years > 0 else principal
                        
                        r = annual_rate / 100  # convert % to decimal
                        n = years
                        # Annual payment formula
                        payment = principal * (r * (1 + r)**n) / ((1 + r)**n - 1)
                        return payment
                    
                    # Calculate system cost
                    system_size_watts = system_capacity_kw * 1000
                    total_system_cost = system_size_watts * system_cost_per_watt
                    incentives = total_system_cost * (incentive_percent / 100)
                    net_system_cost = total_system_cost - incentives
                    annual_maintenance_cost = total_system_cost * (maintenance_cost_percent / 100)

                    # === Loan calculations ===
                    loan_amount = net_system_cost * (loan_percent / 100)          # e.g. 70% financed
                    equity_amount = net_system_cost - loan_amount

                    annual_loan_payment = calculate_loan_payment(
                    principal=loan_amount,
                    annual_rate=loan_interest_rate,
                    years=loan_term_years
                    )

                    years = list(range(1, system_lifetime_years+1))
                    yearly_production = []
                    yearly_maintenance = []

                    yearly_savings_month = [-equity_amount]
                    yearly_savings_15min = [-equity_amount]

                    discounted_yearly_savings_month= [-equity_amount]
                    discounted_yearly_savings_15min= [-equity_amount]                    
                                        
                    yearly_cumulative_savings_month = [-equity_amount]
                    yearly_cumulative_savings_15min = [-equity_amount]             
            
                    cumulative_savings_month = -equity_amount  # Start with negative investment
                    cumulative_savings_15min = -equity_amount  # Start with negative investment

                    year_baseline_cost_list = []                
                    
                    for year in years:
                        prices_csv=f'{tariff}.csv'
                        prices_df=pd.read_csv(prices_csv)
                        # Apply degradation to production
                        year_degradation_factor = (1 - degradation_rate/100) ** (year - 1)
                        year_production_data = production_data * year_degradation_factor 
                        
                        # Apply electricity price increase
                        year_rate_factor = (1 + annual_rate_increase/100) ** (year - 1)
                        ht_lt_cols = [col for col in prices_df.columns if 'HT' in col.upper() or 'LT' in col.upper()]                        

                        # Multiply the selected columns by the factor
                        prices_df[ht_lt_cols] = prices_df[ht_lt_cols] * year_rate_factor
                        #prices_df.to_csv('temp_prices.csv', index=False)
                        #prices_csv_temp='temp_prices.csv'    

                        obracun_energije_month, racuni_month, bilanca_month, godišnji_month = izvrši_obracun(year_production_data,consumption_df,prices_df,net_interval='month')
                        obracun_energije_15min, racuni_15min, bilanca_15min,godišnji_15min = izvrši_obracun(year_production_data,consumption_df,prices_df,net_interval='15min')
                        obracun_energije_noPV, racuni_noPV, bilanca_noPV,godišnji_noPV = izvrši_obracun(no_pv_df,consumption_df,prices_df)

                        total_month = bilanca_month.loc['Year', 'Bill']
                        total_15min = bilanca_15min.loc['Year', 'Bill']
                        total_noPV = bilanca_noPV.loc['Year', 'Bill']

                        year_baseline_cost_list.append(total_noPV)

                        # Calculate baseline cost with rate increase
                        year_baseline_cost = total_noPV
                        # Calculate maintenance with inflation
                        year_maintenance = annual_maintenance_cost * (1 + inflation_rate/100) ** (year - 1)  # Assume 2% inflation 
                        # Calculate savings
                        year_savings_month = year_baseline_cost-year_maintenance-total_month
                        year_savings_15min = year_baseline_cost-year_maintenance-total_15min

                        if year == 10:
                            year_savings_month -= inverter_replacement_cost
                            year_savings_15min -= inverter_replacement_cost

                        # Subtract annual loan payment (only during loan term)
                        if year <= loan_term_years:
                            year_savings_month -= annual_loan_payment
                            year_savings_15min -= annual_loan_payment                        

                        discounted_year_savings_month = year_savings_month / ((1 + discount_rate/100) ** (year-1))
                        discounted_year_savings_15min = year_savings_15min / ((1 + discount_rate/100) ** (year-1))

                        # Update cumulative savings
                        cumulative_savings_month += discounted_year_savings_month
                        cumulative_savings_15min += discounted_year_savings_15min
                                                                                                                                                                
                        year_production=year_production_data['ac_power_kw'].sum()
                        
                        # Store values
                        yearly_production.append(year_production)
                        yearly_maintenance.append(year_maintenance)

                        yearly_savings_15min.append(year_savings_15min)
                        yearly_savings_month.append(year_savings_month)     

                        discounted_yearly_savings_month.append(discounted_year_savings_month)
                        discounted_yearly_savings_15min.append(discounted_year_savings_15min)         

                        yearly_cumulative_savings_month.append(cumulative_savings_month)
                        yearly_cumulative_savings_15min.append(cumulative_savings_15min)
                                        
                    for item in yearly_cumulative_savings_month[1:]:
                        if item >= 0:
                            discounted_payback_years_month = years[yearly_cumulative_savings_month.index(item)-1]
                            break
                        else:
                            discounted_payback_years_month = system_lifetime_years + 1  # If never pays back within lifetime
                    for item in yearly_cumulative_savings_15min[1:]:
                        if item >= 0:
                            discounted_payback_years_15min = years[yearly_cumulative_savings_15min.index(item)-1]
                            break
                        else:
                            discounted_payback_years_15min = system_lifetime_years + 1  # If never pays back within lifetime      

                    # NPV calculation
                    npv_month = sum(discounted_yearly_savings_month)
                    npv_15min =sum(discounted_yearly_savings_15min)

                    # IRR calculation (simplified)
                    try:
                        from scipy.optimize import newton
                        def npv_equation(r):
                            return sum(cf / (1 + r) ** i for i, cf in enumerate(discounted_yearly_savings_month))
                        irr = newton(npv_equation, 0.1)  # Use 10% as initial guess
                    except:
                        irr = 0  # Default if calculation fails"""

                                        # Display financial metrics
                    st.subheader("Pregled financijskih pokazatelja")
                    
                    # Use single column on mobile, three columns on desktop
                    if st.session_state.get('_is_mobile', False):
                        metrics_cols = st.columns(1)
                        metrics_cols[0].metric("Ukupni troškovi SE", f"€{total_system_cost:,.2f}")
                        metrics_cols[0].metric("Neto ukupni troškovi sa subvencijom", f"€{net_system_cost:,.2f}")
                        metrics_cols[0].metric("Početna investicija", f"€{equity_amount:,.2f}")


                        metrics_cols[0].write("Mj.netiranje")
                        metrics_cols[0].metric("Godišnja ušteda (za 1. godinu)", f"€{yearly_savings_month[1]:,.2f}")
                        metrics_cols[0].metric("Vrijeme povrata investicije (diskontirano)", f"{discounted_payback_years_month:.0f} g.")
                        metrics_cols[0].metric("NPV", f"€{npv_month:.1f}")         

                        metrics_cols[0].write("15min netiranje")
                        metrics_cols[0].metric("Godišnja ušteda (za 1. godinu)", f"€{yearly_savings_15min[1]:,.2f}")
                        metrics_cols[0].metric("Vrijeme povrata investicije (diskontirano)", f"{discounted_payback_years_15min:.0f} g.")
                        metrics_cols[0].metric("NPV", f"€{npv_15min:,.2f}")

                        #metrics_cols[0].metric("25-Year ROI", f"{yearly_roi[-1]:.1f}%")
                        #metrics_cols[0].metric("25-Year Net Profit", f"€{yearly_cumulative_savings[-1]:,.2f}")
                    else:
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Ukupni troškovi SE", f"€{total_system_cost:,.2f}")
                        col1.metric("Neto ukupni troškovi sa subvencijom", f"€{net_system_cost:,.2f}")
                        col1.metric("Početna investicija", f"€{equity_amount:,.2f}")
                        #col1.metric("Lista kumulativna", f"{yearly_cumulative_savings_month}")
                        #col1.metric("Lista ušteda", f"{yearly_savings_month}")

                        col2.write("Mj.netiranje")
                        col2.metric("Godišnja ušteda (za 1. godinu)", f"€{yearly_savings_month[1]:,.2f}")
                        col2.metric("Vrijeme povrata investicije (diskontirano)", f"{discounted_payback_years_month:.0f} g."if discounted_payback_years_month <= 25 else "Ne isplati se u 25g")
                        col2.metric("NPV", f"€{npv_month:.2f}")                     
                        
                        col3.write("15min netiranje")
                        col3.metric("Godišnja ušteda (za 1. godinu)", f"€{yearly_savings_15min[1]:,.2f}")
                        col3.metric("Vrijeme povrata investicije (diskontirano)", f"{discounted_payback_years_15min:.0f} g."if discounted_payback_years_15min <= 25 else "Ne isplati se u 25g")
                        col3.metric("NPV", f"€{npv_15min:,.2f}")

                        #col3.metric("25-Year ROI", f"{yearly_roi[-1]:.1f}%")
                        #col3.metric("25-Year Net Profit", f"€{yearly_cumulative_savings[-1]:,.2f}")
                                        # Create cash flow chart
                    st.subheader("25-Year Cash Flow")

                    plot_years = list(range(0, system_lifetime_years+1))
                    # Create DataFrame for cash flow
                    cash_flow_df = pd.DataFrame({
                        'Year': plot_years,
                        'Annual Savings': discounted_yearly_savings_month,
                        'Cumulative Savings': yearly_cumulative_savings_month,
                        'Annual Savings15': discounted_yearly_savings_15min,
                        'Cumulative Savings15': yearly_cumulative_savings_15min,
                    })
                    
                    # Create dual-axis chart
                    fig = go.Figure()
                    
                    # Add annual savings bars
                    fig.add_trace(go.Bar(
                        x=cash_flow_df['Year'],
                        y=cash_flow_df['Annual Savings'],
                        name='Godišnja disk. ušteda (Mj.net)',
                        marker_color='#2ca02c'
                    ))
                    fig.add_trace(go.Bar(
                        x=cash_flow_df['Year'],
                        y=cash_flow_df['Annual Savings15'],
                        name='Godišnja disk. ušteda (15min net)',
                        marker_color="#2c5ea0"
                    ))
                    
                    # Add cumulative savings line
                    fig.add_trace(go.Scatter(
                        x=cash_flow_df['Year'],
                        y=cash_flow_df['Cumulative Savings'],
                        name='Kumulativna ušteda (Mj.net)',
                        marker_color='#ff7f0e',
                        #yaxis='y2'
                    ))

                    # Add cumulative savings line
                    fig.add_trace(go.Scatter(
                        x=cash_flow_df['Year'],
                        y=cash_flow_df['Cumulative Savings15'],
                        name='Kumulativna ušteda (15min net)',
                        marker_color="#ff0e0e",
                        #yaxis='y2'
                    ))
                    
                    # Update layout for dual y-axes
                    fig.update_layout(
                        title='25-god. analiza tokova novca',
                        xaxis=dict(title='Godina'),
                        yaxis=dict(title='God. ušteda (€)', side='left', showgrid=False),
                        #yaxis2=dict(title='Kumulativna ušteda (€)', side='right', overlaying='y', showgrid=False),
                        legend=dict(x=0.5, y=0.99, xanchor='center', orientation='h'),
                        hovermode='x unified'
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)

                    elapsed = time.time() - start_time
                    timer_placeholder.info(f"⏱️ Proteklo vrijeme: **{elapsed:.1f} sekundi**")
                            
                            
                                                   
 

with tabs[5]:
    st.header("Rezultati")

    # Financial inputs section
    #st.subheader("Financijski parametri")
    col1, col2 = st.columns(1) if st.session_state.get('_is_mobile', False) else st.columns(2)

    if st.session_state.get('consumption_data') is not None:
        # Group by month
        monthly_energy = energy_balance.resample('ME').sum()
        monthly_energy.index = monthly_energy.index.strftime('%b')             
        
        st.subheader("Mjesečni pregled bilance energije kod mjesečnog netiranja")
        st.write("Samo mjesečni viškovi proizvedene energije se obračunavaju po cijeni energije isporučene u mrežu, koja je značajno niža od cijene preuzete energije.")
        st.write("U slučaju da je više energije potrošeno nego proizvedeno unutar mjeseca, čitava proizvedena energija je samopotrošena, tj. nema isporučene energije u mrežu.")
        # Create stacked bar chart
        fig = go.Figure()
        
        fig.add_trace(go.Bar(
            x=monthly_energy.index,
            y=monthly_energy['production_kw'],
            name='Proizvodnja',
            marker_color='#2ca02c',
            opacity=1.0
        ))

        fig.add_trace(go.Bar(
            x=monthly_energy.index,
            y=-np.maximum(0, monthly_energy['net_kw']),
            name='Neto višak ',
            marker=dict(
                color='#1f77b4',  
                pattern_shape='/' ,                 # diagonal hatch (most visible)
                # Other good options: 'x', '\\', '|', '-', '+', '.'
                pattern_fillmode='overlay',         # important: draws pattern on top of color
                pattern_fgcolor='#2ca02c',  
                pattern_fgopacity=1,
                pattern_size=24,                     # density of the hatching
                line=dict(color='rgba(214, 39, 40, 0.6)', width=0.5)  # optional thin border
            )
        ))

        fig.add_trace(go.Bar(
            x=monthly_energy.index,
            y=-np.minimum(0, monthly_energy['net_kw']),
            name='Neto manjak ',
            marker_color='#d62728'
            )) 
        
        # Add consumption line
        fig.add_trace(go.Scatter(
            x=monthly_energy.index,
            y=monthly_energy['consumption_kw'],
            name='Potrošnja',
            marker_color='#ff7f0e',
            mode='lines+markers'
        ))
        
        fig.update_layout(
            title='Mjesečna bilanca energije',
            xaxis=dict(title='Mjesec'),
            yaxis=dict(title='Energija (kWh)'),
            barmode='stack',
            legend=dict(x=0.01, y=0.99),
            hovermode='x unified'
        )
        
        st.plotly_chart(fig, use_container_width=True)



        # Create monthly breakdown chart
        st.subheader("Mjesečni pregled bilance energije kod 15minutnog netiranja")
        st.write("Svi viškovi proizvedene energije unutar 15-minutnog perioda se obračunavaju po cijeni energije isporučene u mrežu, koja je značajno niža od cijene preuzete energije.")


        # Create stacked bar chart
        fig = go.Figure()
        
        fig.add_trace(go.Bar(
            x=monthly_energy.index,
            y=monthly_energy['self_consumed_kw'],
            name='Samopotrošnja',
            marker_color='#2ca02c'
        ))

        fig.add_trace(go.Bar(
            x=monthly_energy.index,
            y=monthly_energy['imported_kw'],
            name='Preuzeto iz mreže',
            marker_color='#d62728'
        ))
        fig.add_trace(go.Bar(
            x=monthly_energy.index,
            y=monthly_energy['exported_kw'],
            name='Isporučeno u mrežu',
            marker_color='#1f77b4'
        ))
        
        # Add consumption line
        fig.add_trace(go.Scatter(
            x=monthly_energy.index,
            y=monthly_energy['consumption_kw'],
            name='Potrošnja',
            marker_color='#ff7f0e',
            mode='lines+markers'
        ))
        
        fig.update_layout(
            title='Mjesečna bilanca energije',
            xaxis=dict(title='Mjesec'),
            yaxis=dict(title='Energija (kWh)'),
            barmode='stack',
            legend=dict(x=0.01, y=0.99),
            hovermode='x unified'
        )
        
        st.plotly_chart(fig, use_container_width=True)
                   
        
                
            
    
        
        
        



