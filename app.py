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

# Inicjalizacja stanów (Tylko raz przy starcie)
if 'center' not in st.session_state:
    st.session_state.center = [52.0, 19.0]
if 'zoom' not in st.session_state:
    st.session_state.zoom = 6
if 'sel_id' not in st.session_state:
    st.session_state.sel_id = ""

# --- FUNKCJE ---


def geocode_city(city_name):
    url = f"https://nominatim.openstreetmap.org/search?q={city_name},+Poland&format=json&limit=1"
    try:
        r = httpx.get(
            url, headers={"User-Agent": "GeomexApp/1.0"}, timeout=5.0)
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
            return None, "Błąd"
        wkt = wynik[1]
        coords_raw = re.findall(
            r"([-+]?\d*\.\d+|\d+)\s+([-+]?\d*\.\d+|\d+)", wkt)
        x1, y1 = float(coords_raw[0][0]), float(coords_raw[0][1])

        # Wybór układu 2000
        to_w84 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
        lon, lat = to_w84.transform(x1, y1)
        if lon < 16.5:
            epsg = "EPSG:2176"
        elif lon < 19.5:
            epsg = "EPSG:2177"
        elif lon < 22.5:
            epsg = "EPSG:2178"
        else:
            epsg = "EPSG:2179"

        trans = Transformer.from_crs("EPSG:2180", epsg, always_xy=True)
        pts = [trans.transform(float(x), float(y)) for x, y in coords_raw]
        return pts, epsg
    except:
        return None, "Błąd"


# --- INTERFEJS ---
st.title("🗺️ Geomex")

# 1. Wyszukiwarka (Poza mapą, żeby nie psuła widoku)
with st.container():
    c1, c2 = st.columns([4, 1])
    city_q = c1.text_input("📍 Szukaj adresu", placeholder="Klembów, Marecka")
    if c2.button("Leć do...", use_container_width=True):
        res = geocode_city(city_q)
        if res:
            st.session_state.center = res
            st.session_state.zoom = 18
            st.rerun()

# 2. Mapa (Stabilna)
m = folium.Map(location=st.session_state.center,
               zoom_start=st.session_state.zoom)
folium.WmsTileLayer(url="https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardFull",
                    layers="Raster", name="Orto", overlay=False).add_to(m)
folium.WmsTileLayer(url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
                    layers="dzialki,numery_dzialek", name="Dzialki", transparent=True, overlay=True).add_to(m)

# Kluczowe: st_folium z parametrami zapobiegającymi odświeżaniu
out = st_folium(m, width="100%", height=500,
                key="geomex_map_stable", returned_objects=["last_clicked"])

# 3. Obsługa wyboru działki
if out and out.get("last_clicked"):
    clicked = out["last_clicked"]
    if st.session_state.get('last_coord') != clicked:
        st.session_state.last_coord = clicked
        fid = get_parcel_info(clicked['lng'], clicked['lat'])
        if fid:
            st.session_state.sel_id = fid

# 4. Sekcja Wyników i Pobierania
if st.session_state.sel_id:
    st.info(f"Wybrana działka: **{st.session_state.sel_id}**")

    if st.button("🚀 GENERUJ PLIKI", use_container_width=True, type="primary"):
        pts, epsg = process_parcel(st.session_state.sel_id)
        if pts:
            # TXT
            txt = f"ID: {st.session_state.sel_id}\nUklad: {epsg}\n" + \
                "".join(
                    [f"{i+1}. {p[1]:.2f} {p[0]:.2f}\n" for i, p in enumerate(pts)])
            # DXF
            doc = ezdxf.new()
            msp = doc.modelspace()
            msp.add_lwpolyline(pts, close=True)
            zoom.extents(msp)
            dxf_io = io.StringIO()
            doc.write(dxf_io)
            dxf_v = dxf_io.getvalue()
            # ZIP
            z_io = io.BytesIO()
            with zipfile.ZipFile(z_io, "w") as zf:
                zf.writestr(f"{st.session_state.sel_id}.txt", txt)
                zf.writestr(f"{st.session_state.sel_id}.dxf", dxf_v)

            st.divider()
            st.download_button("📦 POBIERZ ZIP", z_io.getvalue(
            ), f"Geomex_{st.session_state.sel_id}.zip", use_container_width=True)
            c1, c2 = st.columns(2)
            c1.download_button(
                "📄 TXT", txt, f"{st.session_state.sel_id}.txt", use_container_width=True)
            c2.download_button(
                "📐 DXF", dxf_v, f"{st.session_state.sel_id}.dxf", use_container_width=True)
