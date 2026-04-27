import streamlit as st
import httpx
import re
import ezdxf
from ezdxf import zoom
from pyproj import Transformer
import io
import folium
from streamlit_folium import st_folium
import zipfile

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Geomex", page_icon="🗺️", layout="wide")

# 1. Geokodowanie (Szukanie miejscowości)


def geocode_city(city_name):
    url = f"https://nominatim.openstreetmap.org/search?q={city_name},+Poland&format=json&addressdetails=1&limit=1"
    headers = {"User-Agent": "GeomexApp/1.0"}
    try:
        response = httpx.get(url, headers=headers, timeout=10.0)
        data = response.json()
        if data:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            display_name = data[0].get("display_name", city_name)
            return lat, lon, display_name
        return None
    except:
        return None

# 2. Pobieranie ID i adresu z GUGiK (ULDK)


def get_parcel_info(lon, lat):
    # Pobieramy ID
    id_url = f"https://uldk.gugik.gov.pl/?request=GetParcelByXY&xy={lon},{lat},4326&result=id,region,commune,voivodeship"
    try:
        response = httpx.get(id_url, timeout=10.0)
        wynik = response.text.strip().splitlines()
        if wynik and wynik[0] == "0":
            # GUGiK zwraca ID w drugiej linii
            return wynik[1]
        return None
    except:
        return None

# 3. Przeliczanie współrzędnych


def get_epsg_2000(x_1992, y_1992):
    to_wgs84 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
    lon, lat = to_wgs84.transform(x_1992, y_1992)
    if lon < 16.5:
        return "EPSG:2176"
    elif lon < 19.5:
        return "EPSG:2177"
    elif lon < 22.5:
        return "EPSG:2178"
    else:
        return "EPSG:2179"


def process_parcel(identyfikator):
    url = f"https://uldk.gugik.gov.pl/?request=GetParcelById&id={identyfikator}&result=geom_wkt"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = httpx.get(url, headers=headers, timeout=20.0)
        wynik = response.text.strip().splitlines()
        if not wynik or wynik[0] != "0":
            return None, "Błąd GUGiK"
        wkt = wynik[1]
        coords_raw = re.findall(
            r"([-+]?\d*\.\d+|\d+)\s+([-+]?\d*\.\d+|\d+)", wkt)
        x1, y1 = float(coords_raw[0][0]), float(coords_raw[0][1])
        target_epsg = get_epsg_2000(x1, y1)
        transformer = Transformer.from_crs(
            "EPSG:2180", target_epsg, always_xy=True)
        points_2000 = []
        for x_92, y_92 in coords_raw:
            east, north = transformer.transform(float(x_92), float(y_92))
            points_2000.append((east, north))
        return points_2000, target_epsg
    except:
        return None, "Błąd połączenia"


# --- INTERFEJS ---
st.title("🗺️ Geomex - Pobieracz Działek")

if 'map_center' not in st.session_state:
    st.session_state['map_center'] = [52.0, 19.0]
if 'map_zoom' not in st.session_state:
    st.session_state['map_zoom'] = 6
if 'selected_id' not in st.session_state:
    st.session_state['selected_id'] = ""

# Wyszukiwarka
col_s, col_b = st.columns([4, 1])
city_input = col_s.text_input(
    "📍 Wyszukaj miejscowość/adres", placeholder="np. Radom, ul. Lubelska")
if col_b.button("Szukaj", use_container_width=True):
    res = geocode_city(city_input)
    if res:
        st.session_state['map_center'] = [res[0], res[1]]
        st.session_state['map_zoom'] = 17
        st.rerun()

# Mapa
m = folium.Map(
    location=st.session_state['map_center'], zoom_start=st.session_state['map_zoom'])
folium.WmsTileLayer(url="https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardFull",
                    layers="Raster", name="Orto", overlay=False).add_to(m)
folium.WmsTileLayer(url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
                    layers="dzialki,numery_dzialek", name="Działki", transparent=True, overlay=True).add_to(m)

map_data = st_folium(m, width="100%", height=500, key="geomex_map")

# Obsługa kliknięcia (Automatyczne pobieranie ID)
if map_data and map_data.get("last_clicked"):
    lat, lon = map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]
    if st.session_state.get('last_lat_lon') != (lat, lon):
        st.session_state['last_lat_lon'] = (lat, lon)
        with st.spinner("Identyfikowanie działki..."):
            found_id = get_parcel_info(lon, lat)
            if found_id:
                st.session_state['selected_id'] = found_id
                st.rerun()

# Sekcja wyników (zawsze widoczna jeśli ID wybrane)
if st.session_state['selected_id']:
    st.success(
        f"📂 Wybrany identyfikator: **{st.session_state['selected_id']}**")

    # Przycisk generowania
    if st.button("🚀 GENERUJ PLIKI DLA TEJ DZIAŁKI", use_container_width=True, type="primary"):
        punkty, epsg = process_parcel(st.session_state['selected_id'])
        if punkty:
            # Tworzenie plików
            txt = f"Dzialka: {st.session_state['selected_id']}\nUklad: {epsg}\n" + "".join(
                [f"{i+1}. {p[1]:.2f} {p[0]:.2f}\n" for i, p in enumerate(punkty)])

            doc = ezdxf.new()
            msp = doc.modelspace()
            msp.add_lwpolyline(punkty, close=True)
            zoom.extents(msp)
            dxf_io = io.StringIO()
            doc.write(dxf_io)

            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, "w") as zf:
                zf.writestr(f"{st.session_state['selected_id']}.txt", txt)
                zf.writestr(
                    f"{st.session_state['selected_id']}.dxf", dxf_io.getvalue())

            st.divider()
            st.download_button("📦 POBIERZ KOMPLET (ZIP)", zip_io.getvalue(
            ), f"Geomex_{st.session_state['selected_id']}.zip", "application/zip", use_container_width=True)
            col1, col2 = st.columns(2)
            col1.download_button(
                "📄 Tylko TXT", txt, f"{st.session_state['selected_id']}.txt", use_container_width=True)
            col2.download_button("📐 Tylko DXF", dxf_io.getvalue(
            ), f"{st.session_state['selected_id']}.dxf", use_container_width=True)
