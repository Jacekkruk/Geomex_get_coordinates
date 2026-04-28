import streamlit as st
import httpx
import re
import ezdxf
from ezdxf import zoom
from pyproj import Transformer
import io
import folium
from folium.plugins import Fullscreen
from streamlit_folium import st_folium
import zipfile

# --- KONFIGURACJA STRONY ---
# Ustawienie ikony i tytułu w sposób standardowy (najbezpieczniejszy)
st.set_page_config(
    page_title="GEOMEX",
    page_icon="🗺️",  # Możesz tu wstawić URL do logo.png jeśli jest publiczne
    layout="wide"
)

# Prosty i bezpieczny CSS
st.markdown(
    """
    <style>
        /* Marginesy boczne ułatwiające przewijanie na telefonie */
        .stMainContainer {
            padding-left: 5% !important;
            padding-right: 5% !important;
        }
        /* Ukrycie zbędnych elementów Streamlit */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        /* Naprawa czarnego tła mapy */
        .stfolium {
            background-color: transparent !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- INICJALIZACJA STANU ---
if "center" not in st.session_state:
    st.session_state.center = [52.0, 19.0]
if "zoom" not in st.session_state:
    st.session_state.zoom = 6
if "sel_id" not in st.session_state:
    st.session_state.sel_id = ""

# --- FUNKCJE POMOCNICZE ---


def geocode_city(city_name: str):
    url = f"https://nominatim.openstreetmap.org/search?q={city_name}, Poland&format=json&limit=1"
    try:
        r = httpx.get(
            url, headers={"User-Agent": "GeomexApp/1.1"}, timeout=5.0)
        data = r.json()
        if data:
            return [float(data[0]["lat"]), float(data[0]["lon"])]
    except:
        return None


def get_parcel_info(lon, lat):
    url = f"https://uldk.gugik.gov.pl/?request=GetParcelByXY&xy={lon},{lat},4326&result=id"
    try:
        r = httpx.get(url, timeout=5.0)
        wynik = r.text.strip().splitlines()
        if wynik and wynik[0] == "0":
            return wynik[1]
    except:
        return None


def process_parcel(identyfikator):
    url = f"https://uldk.gugik.gov.pl/?request=GetParcelById&id={identyfikator}&result=geom_wkt"
    try:
        r = httpx.get(url, timeout=10.0)
        wynik = r.text.strip().splitlines()
        if not wynik or wynik[0] != "0":
            return None, "Błąd pobierania"
        wkt = wynik[1]
        coords_raw = re.findall(
            r"([-+]?\d*\.\d+|\d+)\s+([-+]?\d*\.\d+|\d+)", wkt)
        x1, y1 = float(coords_raw[0][0]), float(coords_raw[0][1])
        to_wgs84 = Transformer.from_crs(
            "EPSG:2180", "EPSG:4326", always_xy=True)
        lon, lat = to_wgs84.transform(x1, y1)
        epsg = "EPSG:2176" if lon < 16.5 else "EPSG:2177" if lon < 19.5 else "EPSG:2178" if lon < 22.5 else "EPSG:2179"
        transformer = Transformer.from_crs("EPSG:2180", epsg, always_xy=True)
        pts = [transformer.transform(float(x), float(y))
               for x, y in coords_raw]
        return pts, epsg
    except:
        return None, "Błąd"


# --- INTERFEJS ---
st.title("🗺️ GEOMEX")

# Prosta wyszukiwarka
c1, c2 = st.columns([3, 1])
city_q = c1.text_input("📍 Szukaj miejscowości",
                       placeholder="np. Klembów, Marecka")
if c2.button("Szukaj", use_container_width=True):
    res = geocode_city(city_q)
    if res:
        st.session_state.center = res
        st.session_state.zoom = 18
        st.rerun()

# MAPA
m = folium.Map(location=st.session_state.center,
               zoom_start=st.session_state.zoom)
folium.WmsTileLayer(url="https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardFull",
                    layers="Raster", name="Satelita", overlay=False).add_to(m)
folium.WmsTileLayer(url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
                    layers="dzialki,numery_dzialek", name="Działki", transparent=True, overlay=True).add_to(m)

# Wyświetlenie mapy - ZMNIEJSZONA wysokość dla lepszego przewijania na tel
out = st_folium(m, width="100%", height=400, key="main_map")

if out and out.get("last_clicked"):
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    with st.spinner("Szukam działki..."):
        fid = get_parcel_info(lon, lat)
        if fid:
            st.session_state.sel_id = fid

# Panel dolny
if st.session_state.sel_id:
    st.success(f"Działka: {st.session_state.sel_id}")
    if st.button("🚀 GENERUJ DXF/TXT", use_container_width=True, type="primary"):
        pts, epsg = process_parcel(st.session_state.sel_id)
        if pts:
            # TXT
            txt = f"ID: {st.session_state.sel_id}\nUklad: {epsg}\n" + "".join(
                [f"{i+1}. X={p[0]:.2f} Y={p[1]:.2f}\n" for i, p in enumerate(pts)])
            # DXF
            doc = ezdxf.new()
            msp = doc.modelspace()
            msp.add_lwpolyline(pts, close=True)
            zoom.extents(msp)
            d_io = io.StringIO()
            doc.write(d_io)
            # ZIP
            z_io = io.BytesIO()
            with zipfile.ZipFile(z_io, "w") as zf:
                zf.writestr(f"{st.session_state.sel_id}.txt", txt)
                zf.writestr(f"{st.session_state.sel_id}.dxf", d_io.getvalue())

            st.download_button("📦 POBIERZ ZIP", z_io.getvalue(
            ), f"Geomex_{st.session_state.sel_id}.zip", use_container_width=True)
