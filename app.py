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

# 1. Funkcja: Wyszukiwanie miejscowości (Geocoding)


def geocode_city(city_name):
    url = f"https://nominatim.openstreetmap.org/search?q={city_name},+Poland&format=json&limit=1"
    headers = {"User-Agent": "GeomexApp/1.0"}
    try:
        response = httpx.get(url, headers=headers, timeout=10.0)
        data = response.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
        return None
    except:
        return None

# 2. Funkcja: Pobieranie ID działki po kliknięciu na mapie (XY)


def get_id_by_xy(lon, lat):
    url = f"https://uldk.gugik.gov.pl/?request=GetParcelByXY&xy={lon},{lat},4326&result=id"
    try:
        response = httpx.get(url, timeout=10.0)
        wynik = response.text.strip().splitlines()
        if wynik and wynik[0] == "0":
            return wynik[1]
        return None
    except:
        return None

# 3. Funkcja: Wybór strefy układu 2000 (5, 6, 7 lub 8)


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

# 4. Funkcja: Pobieranie geometrii działki i konwersja do 2000


def process_parcel(identyfikator):
    url = f"https://uldk.gugik.gov.pl/?request=GetParcelById&id={identyfikator}&result=geom_wkt"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = httpx.get(url, headers=headers, timeout=20.0)
        wynik = response.text.strip().splitlines()
        if not wynik or wynik[0] != "0":
            return None, "Błąd pobierania danych z GUGiK."

        wkt = wynik[1]
        coords_raw = re.findall(
            r"([-+]?\d*\.\d+|\d+)\s+([-+]?\d*\.\d+|\d+)", wkt)
        if not coords_raw:
            return None, "Błąd odczytu geometrii."

        # Ustalenie strefy na podstawie pierwszego punktu
        x1, y1 = float(coords_raw[0][0]), float(coords_raw[0][1])
        target_epsg = get_epsg_2000(x1, y1)

        transformer = Transformer.from_crs(
            "EPSG:2180", target_epsg, always_xy=True)

        points_2000 = []
        for x_92, y_92 in coords_raw:
            east, north = transformer.transform(float(x_92), float(y_92))
            points_2000.append((east, north))

        return points_2000, target_epsg
    except Exception as e:
        return None, str(e)


# --- INTERFEJS UŻYTKOWNIKA ---
st.title("🗺️ Geomex - Pobieracz Działek DXF")

# Inicjalizacja pamięci sesji (żeby mapa nie skakała)
if 'map_center' not in st.session_state:
    st.session_state['map_center'] = [52.0, 19.0]
if 'map_zoom' not in st.session_state:
    st.session_state['map_zoom'] = 6
if 'selected_id' not in st.session_state:
    st.session_state['selected_id'] = ""

tab1, tab2 = st.tabs(["📍 Mapa i wyszukiwarka", "⌨️ Wpisz ID ręcznie"])

with tab1:
    # Wyszukiwarka miejscowości
    col_search, col_btn = st.columns([4, 1])
    city_to_find = col_search.text_input(
        "Gdzie szukać?", placeholder="Wpisz miasto lub adres (np. Radom, ul. Główna)")
    if col_btn.button("Szukaj 🔍", use_container_width=True):
        if city_to_find:
            coords = geocode_city(city_to_find)
            if coords:
                st.session_state['map_center'] = coords
                st.session_state['map_zoom'] = 16
                st.rerun()
            else:
                st.error("Nie znaleziono miejscowości.")

    st.info("Przybliż mapę i kliknij w wybraną działkę. Numery pojawią się przy dużym zbliżeniu.")

    # Budowa mapy z warstwami Geoportalu
    m = folium.Map(
        location=st.session_state['map_center'], zoom_start=st.session_state['map_zoom'])

    # 1. Podkład - Zdjęcia satelitarne (Ortofotomapa)
    folium.WmsTileLayer(
        url="https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardFull",
        layers="Raster", name="Ortofotomapa", fmt="image/png", transparent=True, overlay=False
    ).add_to(m)

    # 2. Warstwa - Granice działek
    folium.WmsTileLayer(
        url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
        layers="dzialki", name="Granice", fmt="image/png", transparent=True, overlay=True
    ).add_to(m)

    # 3. Warstwa - Numery działek (Teksty)
    folium.WmsTileLayer(
        url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
        layers="numery_dzialek", name="Numery działek", fmt="image/png", transparent=True, overlay=True
    ).add_to(m)

    # Wyświetlenie mapy w Streamlit
    output = st_folium(m, width="100%", height=550, key="geomex_map_v1")

    # Obsługa kliknięcia w mapę
    if output and output.get("last_clicked"):
        lat, lon = output["last_clicked"]["lat"], output["last_clicked"]["lng"]
        st.session_state['map_center'] = [lat, lon]
        st.session_state['map_zoom'] = 18

        with st.spinner("Pobieranie numeru działki..."):
            found_id = get_id_by_xy(lon, lat)
            if found_id:
                st.session_state['selected_id'] = found_id
                st.success(f"Wybrano działkę: {found_id}")

with tab2:
    manual_input = st.text_input(
        "Podaj pełny identyfikator działki", value=st.session_state['selected_id'])
    if manual_input:
        st.session_state['selected_id'] = manual_input

# --- PROCES GENEROWANIA PLIKÓW ---
final_id = st.session_state['selected_id']

if st.button("🚀 Przygotuj dane do pobrania", use_container_width=True):
    if final_id:
        with st.spinner('Trwa generowanie plików...'):
            punkty, epsg_result = process_parcel(final_id)

            if punkty:
                # A. Tekstowy (TXT)
                txt_content = f"ID: {final_id}\nUklad: {epsg_result}\nFormat: Nr. X(Polnocna) Y(Wschodnia)\n" + \
                    "-"*40 + "\n"
                for i, (e, n) in enumerate(punkty, start=1):
                    txt_content += f"{i}. {n:.2f} {e:.2f}\n"

                # B. CAD (DXF)
                doc = ezdxf.new('R2010')
                msp = doc.modelspace()
                msp.add_lwpolyline(punkty, close=True, dxfattribs={'color': 1})
                for i, (e, n) in enumerate(punkty, start=1):
                    msp.add_text(str(i), dxfattribs={'height': 0.8}).set_placement(
                        (e+0.5, n+0.5))
                zoom.extents(msp)
                dxf_buf = io.StringIO()
                doc.write(dxf_buf)
                dxf_data = dxf_buf.getvalue()

                # C. Paczka ZIP (Oba pliki razem)
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(f"dzialka_{final_id}.txt", txt_content)
                    zf.writestr(f"dzialka_{final_id}.dxf", dxf_data)

                st.divider()
                st.subheader("Gotowe! Wybierz sposób pobrania:")

                # Przycisk zbiorczy
                st.download_button(
                    label="📦 POBIERZ PAKIET (TXT + DXF w ZIP)",
                    data=zip_buf.getvalue(),
                    file_name=f"Geomex_{final_id}.zip",
                    mime="application/zip",
                    use_container_width=True
                )

                # Przyciski pojedyncze
                c1, c2 = st.columns(2)
                c1.download_button("📄 Tylko plik TXT", data=txt_content,
                                   file_name=f"{final_id}.txt", use_container_width=True)
                c2.download_button("📐 Tylko plik DXF", data=dxf_data,
                                   file_name=f"{final_id}.dxf", use_container_width=True)
            else:
                st.error(f"Błąd: {epsg_result}")
    else:
        st.warning("Najpierw wybierz działkę na mapie lub wpisz jej numer.")
