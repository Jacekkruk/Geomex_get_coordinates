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

# Funkcje pomocnicze


def geocode_city(city_name):
    url = f"https://nominatim.openstreetmap.org/search?q={city_name},+Poland&format=json&limit=1"
    headers = {"User-Agent": "GeomexApp/1.0"}
    try:
        response = httpx.get(url, headers=headers, timeout=5.0)
        data = response.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
        return None
    except:
        return None


def get_parcel_info(lon, lat):
    url = f"https://uldk.gugik.gov.pl/?request=GetParcelByXY&xy={lon},{lat},4326&result=id"
    try:
        response = httpx.get(url, timeout=5.0)
        wynik = response.text.strip().splitlines()
        if wynik and wynik[0] == "0":
            return wynik[1]
        return None
    except:
        return None


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
    try:
        response = httpx.get(url, timeout=10.0)
        wynik = response.text.strip().splitlines()
        if not wynik or wynik[0] != "0":
            return None, "Błąd"
        wkt = wynik[1]
        coords_raw = re.findall(
            r"([-+]?\d*\.\d+|\d+)\s+([-+]?\d*\.\d+|\d+)", wkt)
        x1, y1 = float(coords_raw[0][0]), float(coords_raw[0][1])
        target_epsg = get_epsg_2000(x1, y1)
        transformer = Transformer.from_crs(
            "EPSG:2180", target_epsg, always_xy=True)
        points = [transformer.transform(float(x), float(y))
                  for x, y in coords_raw]
        return points, target_epsg
    except:
        return None, "Błąd"


# --- LOGIKA APLIKACJI ---
if 'center' not in st.session_state:
    st.session_state.center = [52.0, 19.0]
if 'zoom' not in st.session_state:
    st.session_state.zoom = 6
if 'sel_id' not in st.session_state:
    st.session_state.sel_id = ""

st.title("🗺️ Geomex - Pobieracz Działek")

# Wyszukiwarka
c1, c2 = st.columns([4, 1])
city = c1.text_input("📍 Miejscowość / Adres",
                     placeholder="np. Klembów, Marecka")
if c2.button("Szukaj", use_container_width=True):
    coords = geocode_city(city)
    if coords:
        st.session_state.center = coords
        st.session_state.zoom = 17
        st.rerun()

# Mapa
m = folium.Map(location=st.session_state.center,
               zoom_start=st.session_state.zoom)
folium.WmsTileLayer(url="https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardFull",
                    layers="Raster", name="Orto", overlay=False).add_to(m)
folium.WmsTileLayer(url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
                    layers="dzialki,numery_dzialek", name="Działki", transparent=True, overlay=True).add_to(m)

out = st_folium(m, width="100%", height=500, key="mapa_v3")

# Kliknięcie
if out and out.get("last_clicked"):
    cur_lat, cur_lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    # Pobieramy ID tylko jeśli kliknięto w nowe miejsce
    if st.session_state.get('last_click') != (cur_lat, cur_lon):
        st.session_state.last_click = (cur_lat, cur_lon)
        with st.spinner("Identyfikowanie..."):
            fid = get_parcel_info(cur_lon, cur_lat)
            if fid:
                st.session_state.sel_id = fid
                st.rerun()

# Wyniki
if st.session_state.sel_id:
    st.success(f"📍 Wybrano: **{st.session_state.sel_id}**")
    if st.button("🚀 PRZYGOTUJ PLIKI", use_container_width=True, type="primary"):
        pts, epsg = process_parcel(st.session_state.sel_id)
        if pts:
            # Plik TXT
            txt = f"ID: {st.session_state.sel_id}\nUklad: {epsg}\n" + \
                "".join(
                    [f"{i+1}. {p[1]:.2f} {p[0]:.2f}\n" for i, p in enumerate(pts)])
            # Plik DXF
            doc = ezdxf.new()
            msp = doc.modelspace()
            msp.add_lwpolyline(pts, close=True)
            zoom.extents(msp)
            dxf_io = io.StringIO()
            doc.write(dxf_io)
            dxf_val = dxf_io.getvalue()
            # ZIP
            z_io = io.BytesIO()
            with zipfile.ZipFile(z_io, "w") as zf:
                zf.writestr(f"{st.session_state.sel_id}.txt", txt)
                zf.writestr(f"{st.session_state.sel_id}.dxf", dxf_val)

            st.divider()
            st.download_button("📦 POBIERZ ZIP", z_io.getvalue(
            ), f"Geomex_{st.session_state.sel_id}.zip", use_container_width=True)
            col1, col2 = st.columns(2)
            col1.download_button(
                "📄 TXT", txt, f"{st.session_state.sel_id}.txt", use_container_width=True)
            col2.download_button(
                "📐 DXF", dxf_val, f"{st.session_state.sel_id}.dxf", use_container_width=True)
