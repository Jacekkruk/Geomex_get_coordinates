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
    page_icon="logo.png",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Ukrycie brandingu Streamlit
st.markdown("""
    <style>
        #MainMenu, footer, header {visibility: hidden;}
        .stDeployButton {display: none;}
    </style>
""", unsafe_allow_html=True)

# --- INICJALIZACJA STANU ---
if "center" not in st.session_state:
    st.session_state.center = [52.0, 19.0]
if "zoom" not in st.session_state:
    st.session_state.zoom = 6
if "sel_id" not in st.session_state:
    st.session_state.sel_id = ""
if "last_coord" not in st.session_state:
    st.session_state.last_coord = None


# --- FUNKCJE ---
def geocode_city(city_name: str):
    """Wyszukiwanie lokalizacji przez Nominatim."""
    if not city_name:
        return None

    url = (
        f"https://nominatim.openstreetmap.org/search?"
        f"q={city_name}, Poland&format=json&limit=1"
    )
    try:
        r = httpx.get(
            url,
            headers={"User-Agent": "GeomexApp/1.0"},
            timeout=5.0,
        )
        r.raise_for_status()
        data = r.json()
        if data:
            return [float(data[0]["lat"]), float(data[0]["lon"])]
    except Exception:
        return None

    return None


def get_parcel_info(lon: float, lat: float):
    """Pobiera identyfikator działki na podstawie kliknięcia na mapie."""
    url = (
        "https://uldk.gugik.gov.pl/"
        f"?request=GetParcelByXY&xy={lon},{lat},4326&result=id"
    )
    try:
        r = httpx.get(url, timeout=5.0)
        r.raise_for_status()
        wynik = r.text.strip().splitlines()
        if wynik and wynik[0] == "0":
            return wynik[1]
    except Exception:
        return None

    return None


def process_parcel(identyfikator: str):
    """Pobiera geometrię działki i przelicza współrzędne do odpowiedniej strefy układu 2000."""
    url = (
        "https://uldk.gugik.gov.pl/"
        f"?request=GetParcelById&id={identyfikator}&result=geom_wkt"
    )

    try:
        r = httpx.get(url, timeout=10.0)
        r.raise_for_status()
        wynik = r.text.strip().splitlines()

        if not wynik or wynik[0] != "0":
            return None, "Błąd pobierania geometrii"

        wkt = wynik[1]
        coords_raw = re.findall(
            r"([-+]?\d*\.\d+|\d+)\s+([-+]?\d*\.\d+|\d+)",
            wkt,
        )

        if not coords_raw:
            return None, "Brak geometrii"

        x1, y1 = float(coords_raw[0][0]), float(coords_raw[0][1])

        # Określenie właściwej strefy PL-2000
        to_wgs84 = Transformer.from_crs(
            "EPSG:2180", "EPSG:4326", always_xy=True)
        lon, lat = to_wgs84.transform(x1, y1)

        if lon < 16.5:
            epsg = "EPSG:2176"
        elif lon < 19.5:
            epsg = "EPSG:2177"
        elif lon < 22.5:
            epsg = "EPSG:2178"
        else:
            epsg = "EPSG:2179"

        transformer = Transformer.from_crs("EPSG:2180", epsg, always_xy=True)
        pts = [
            transformer.transform(float(x), float(y))
            for x, y in coords_raw
        ]

        return pts, epsg

    except Exception as e:
        return None, f"Błąd: {e}"


# --- INTERFEJS ---
st.title("🗺️ Geomex")

# --- TRYB WYSZUKIWANIA ---

# Ułatwienie przewijania na urządzeniach mobilnych
st.markdown(
    """
    <style>
    iframe[title="streamlit_folium.st_folium"] {
        touch-action: pan-y !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- WYSZUKIWARKA ---
with st.container():
    c1, c2 = st.columns([4, 1])

    city_q = c1.text_input(
        "📍 Wyszukaj lokalizację lub wpisz identyfikator działki",
        placeholder="np. Klembów, ul. Marecka lub 146504_8.0603.8/11",
    ),

    if c2.button("Leć do...", use_container_width=True):
        query = str(city_q).strip()

        if not query:
            st.warning("Wpisz adres, miejscowość lub identyfikator działki.")
        elif re.match(r"^\d{6}_\d\.\d{4}\.\d+/\d+$", query):
            st.session_state.sel_id = query
            st.success(f"Wczytano działkę: {query}")
        else:
            res = geocode_city(query)
            if res:
                st.session_state.center = res
                st.session_state.zoom = 18
                st.rerun()
            else:
                st.warning("Nie znaleziono lokalizacji ani działki.")


# --- MAPA ---
m = folium.Map(
    location=st.session_state.center,
    zoom_start=st.session_state.zoom,
    tiles="OpenStreetMap",
    control_scale=True,
)

# Warstwa bazowa OSM
folium.TileLayer(
    "OpenStreetMap",
    name="Mapa standardowa",
    overlay=False,
    control=True,
).add_to(m)

# Ortofotomapa Geoportalu
folium.WmsTileLayer(
    url="https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardFull",
    layers="Raster",
    name="Ortofotomapa",
    fmt="image/png",
    transparent=True,
    overlay=True,
    control=True,
).add_to(m)

# Granice i numery działek
folium.WmsTileLayer(
    url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
    layers="dzialki",
    name="Działki ewidencyjne",
    fmt="image/png",
    transparent=True,
    overlay=True,
    control=True,
).add_to(m)

# Dodatki
Fullscreen().add_to(m)
folium.LayerControl().add_to(m)

# Render mapy
out = st_folium(
    m,
    width=None,
    height=420,
    key="geomex_map_stable",
    returned_objects=["last_clicked"],
)


# --- OBSŁUGA KLIKNIĘCIA ---
if out and out.get("last_clicked"):
    clicked = out["last_clicked"]

    if st.session_state.last_coord != clicked:
        st.session_state.last_coord = clicked

        fid = get_parcel_info(clicked["lng"], clicked["lat"])
        if fid:
            st.session_state.sel_id = fid


# --- WYNIKI I POBIERANIE ---
if st.session_state.sel_id:
    st.info(f"Wybrana działka: **{st.session_state.sel_id}**")

    if st.button(
        "🚀 GENERUJ PLIKI",
        use_container_width=True,
        type="primary",
    ):
        with st.spinner("Generowanie plików..."):
            pts, epsg = process_parcel(st.session_state.sel_id)

            if pts:
                # TXT
                txt = (
                    f"ID działki: {st.session_state.sel_id}\n"
                    f"Układ współrzędnych: {epsg}\n\n"
                )

                for i, p in enumerate(pts, start=1):
                    txt += f"{i}. X={p[0]:.2f} Y={p[1]:.2f}\n"

                # DXF
                doc = ezdxf.new("R2010")
                msp = doc.modelspace()
                msp.add_lwpolyline(pts, close=True)
                zoom.extents(msp)

                dxf_io = io.StringIO()
                doc.write(dxf_io)
                dxf_data = dxf_io.getvalue()

                # ZIP
                zip_io = io.BytesIO()
                with zipfile.ZipFile(zip_io, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(f"{st.session_state.sel_id}.txt", txt)
                    zf.writestr(f"{st.session_state.sel_id}.dxf", dxf_data)

                st.success("Pliki zostały wygenerowane.")
                st.divider()

                st.download_button(
                    "📦 Pobierz ZIP",
                    zip_io.getvalue(),
                    file_name=f"Geomex_{st.session_state.sel_id}.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

                c1, c2 = st.columns(2)

                with c1:
                    st.download_button(
                        "📄 Pobierz TXT",
                        txt,
                        file_name=f"{st.session_state.sel_id}.txt",
                        mime="text/plain",
                        use_container_width=True,
                    )

                with c2:
                    st.download_button(
                        "📐 Pobierz DXF",
                        dxf_data,
                        file_name=f"{st.session_state.sel_id}.dxf",
                        mime="application/dxf",
                        use_container_width=True,
                    )
            else:
                st.error(f"Nie udało się przetworzyć działki. {epsg}")
