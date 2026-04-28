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
st.set_page_config(
    page_title="Geomex_XY",
    page_icon="https://cdn-icons-png.flaticon.com/512/854/854878.png",
    layout="centered"
)

# Styl CSS naprawiający przewijanie na telefonie i ukrywający branding
st.markdown(
    """
    <style>
        /* Dodanie marginesu, aby dało się przewijać stronę palcem obok mapy */
        .main .block-container {
            padding-left: 2rem;
            padding-right: 2rem;
        }
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
    </style>
    <script>
        window.parent.document.title = "GEOMEX";
    </script>
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
if "last_coord" not in st.session_state:
    st.session_state.last_coord = None

# --- FUNKCJE POMOCNICZE ---


def geocode_city(city_name: str):
    url = f"https://nominatim.openstreetmap.org/search?q={city_name}, Poland&format=json&limit=1"
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
    except Exception as e:
        return None, str(e)


# --- INTERFEJS ---
st.title("🗺️ Geomex")

# Zakładki: Wybór metody
tab_map, tab_id = st.tabs(["📍 Szukaj na mapie", "⌨️ Wpisz nr działki"])

with tab_id:
    st.subheader("Wpisz identyfikator")
    manual_id = st.text_input(
        "Identyfikator działki", value=st.session_state.sel_id, placeholder="np. 143407_2.0005.20")
    if manual_id:
        st.session_state.sel_id = manual_id

with tab_map:
    # Wyszukiwarka miejscowości
    c1, c2 = st.columns([3, 1])
    city_q = c1.text_input("📍 Miejscowość", placeholder="Klembów, Marecka")
    if c2.button("Leć", use_container_width=True):
        res = geocode_city(city_q)
        if res:
            st.session_state.center = res
            st.session_state.zoom = 18
            st.rerun()

    # Mapa
    m = folium.Map(location=st.session_state.center,
                   zoom_start=st.session_state.zoom, control_scale=True)
    folium.TileLayer("OpenStreetMap", name="OSM", overlay=False).add_to(m)
    folium.WmsTileLayer(url="https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardFull",
                        layers="Raster", name="Satelita", transparent=True, overlay=True).add_to(m)
    folium.WmsTileLayer(url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
                        layers="dzialki,numery_dzialek", name="Działki", transparent=True, overlay=True).add_to(m)
    Fullscreen().add_to(m)
    folium.LayerControl().add_to(m)

    out = st_folium(m, width="100%", height=450,
                    key="geomex_map", returned_objects=["last_clicked"])

    if out and out.get("last_clicked"):
        clicked = out["last_clicked"]
        if st.session_state.last_coord != clicked:
            st.session_state.last_coord = clicked
            fid = get_parcel_info(clicked["lng"], clicked["lat"])
            if fid:
                st.session_state.sel_id = fid
                st.rerun()

# --- PANEL POBIERANIA (Zawsze na widoku, gdy wybrano działkę) ---
if st.session_state.sel_id:
    st.divider()
    st.success(f"Wybrana działka: **{st.session_state.sel_id}**")

    if st.button("🚀 GENERUJ PLIKI", use_container_width=True, type="primary"):
        with st.spinner("Przetwarzanie..."):
            pts, epsg = process_parcel(st.session_state.sel_id)
            if pts:
                # Generowanie TXT
                txt = f"ID: {st.session_state.sel_id}\nUklad: {epsg}\n" + "".join(
                    [f"{i+1}. X={p[0]:.2f} Y={p[1]:.2f}\n" for i, p in enumerate(pts)])

                # Generowanie DXF
                doc = ezdxf.new("R2010")
                msp = doc.modelspace()
                msp.add_lwpolyline(pts, close=True)
                zoom.extents(msp)
                dxf_io = io.StringIO()
                doc.write(dxf_io)
                dxf_data = dxf_io.getvalue()

                # Generowanie ZIP
                zip_io = io.BytesIO()
                with zipfile.ZipFile(zip_io, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(f"{st.session_state.sel_id}.txt", txt)
                    zf.writestr(f"{st.session_state.sel_id}.dxf", dxf_data)

                # Przyciski pobierania
                st.download_button("📦 Pobierz komplet (ZIP)", zip_io.getvalue(
                ), f"Geomex_{st.session_state.sel_id}.zip", "application/zip", use_container_width=True)
                c1, c2 = st.columns(2)
                c1.download_button(
                    "📄 TXT", txt, f"{st.session_state.sel_id}.txt", use_container_width=True)
                c2.download_button(
                    "📐 DXF", dxf_data, f"{st.session_state.sel_id}.dxf", use_container_width=True)
            else:
                st.error("Nie znaleziono geometrii dla tego numeru.")
