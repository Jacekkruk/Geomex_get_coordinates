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

# Funkcja do wyszukiwania współrzędnych miejscowości (Geocoding)


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


# --- INTERFEJS UŻYTKOWNIKA ---
st.title("🗺️ Geomex - Interaktywna Mapa Działek")

# Inicjalizacja stanu mapy
if 'map_center' not in st.session_state:
    st.session_state['map_center'] = [52.0, 19.0]
if 'map_zoom' not in st.session_state:
    st.session_state['map_zoom'] = 6
if 'selected_id' not in st.session_state:
    st.session_state['selected_id'] = ""

tab1, tab2 = st.tabs(["📍 Wybierz z mapy", "⌨️ Wpisz ręcznie"])

with tab1:
    # Sekcja wyszukiwania miejscowości
    col_search, col_btn = st.columns([4, 1])
    city_to_find = col_search.text_input(
        "Wpisz miejscowość, aby przybliżyć", placeholder="np. Warszawa, ul. Jasna")
    if col_btn.button("Szukaj 🔍", use_container_width=True):
        if city_to_find:
            coords = geocode_city(city_to_find)
            if coords:
                st.session_state['map_center'] = coords
                # Duże przybliżenie na miasto
                st.session_state['map_zoom'] = 15
                st.rerun()  # Odświeżenie strony, by mapa się przemieściła
            else:
                st.error("Nie znaleziono takiej miejscowości.")

    st.info("Przybliż mapę i kliknij w środek działki.")

    # Tworzenie mapy z aktualnym środkiem i zoomem
    m = folium.Map(
        location=st.session_state['map_center'],
        zoom_start=st.session_state['map_zoom']
    )

    folium.WmsTileLayer(
        url="https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardFull",
        layers="Raster", name="Ortofotomapa", fmt="image/png", transparent=True, overlay=False
    ).add_to(m)
    folium.WmsTileLayer(
        url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
        layers="dzialki", name="Działki", fmt="image/png", transparent=True, overlay=True
    ).add_to(m)

    output = st_folium(m, width="100%", height=500, key="geomex_map")

    if output and output.get("last_clicked"):
        lat, lon = output["last_clicked"]["lat"], output["last_clicked"]["lng"]
        # Aktualizujemy środek mapy, żeby po kliknięciu nie wracała do poprzedniego widoku
        st.session_state['map_center'] = [lat, lon]
        st.session_state['map_zoom'] = 18

        with st.spinner("Identyfikowanie działki..."):
            found_id = get_id_by_xy(lon, lat)
            if found_id:
                st.session_state['selected_id'] = found_id
                st.success(f"Wybrana działka: {found_id}")

with tab2:
    input_id = st.text_input("Identyfikator działki",
                             value=st.session_state['selected_id'])
    if input_id:
        st.session_state['selected_id'] = input_id

# --- GENEROWANIE PLIKÓW ---
final_id = st.session_state['selected_id']

if st.button("🚀 Przygotuj paczkę danych", use_container_width=True):
    if final_id:
        with st.spinner('Przetwarzanie...'):
            punkty, epsg_result = process_parcel(final_id)
            if punkty:
                # Generowanie TXT
                txt_content = f"ID: {final_id}\nUklad: {epsg_result}\n"
                for i, (e, n) in enumerate(punkty, start=1):
                    txt_content += f"{i}. {n:.2f} {e:.2f}\n"

                # Generowanie DXF
                doc = ezdxf.new('R2010')
                msp = doc.modelspace()
                msp.add_lwpolyline(punkty, close=True, dxfattribs={'color': 1})
                for i, (e, n) in enumerate(punkty, start=1):
                    msp.add_text(str(i), dxfattribs={'height': 0.8}).set_placement(
                        (e+0.5, n+0.5))
                zoom.extents(msp)
                dxf_buffer = io.StringIO()
                doc.write(dxf_buffer)
                dxf_data = dxf_buffer.getvalue()

                # Generowanie ZIP
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zf:
                    zf.writestr(f"{final_id}.txt", txt_content)
                    zf.writestr(f"{final_id}.dxf", dxf_data)

                st.divider()
                st.download_button("📦 POBIERZ WSZYSTKO (ZIP)", data=zip_buffer.getvalue(),
                                   file_name=f"Geomex_{final_id}.zip", mime="application/zip", use_container_width=True)

                c1, c2 = st.columns(2)
                c1.download_button("📄 Tylko TXT", data=txt_content,
                                   file_name=f"{final_id}.txt", use_container_width=True)
                c2.download_button("📐 Tylko DXF", data=dxf_data,
                                   file_name=f"{final_id}.dxf", use_container_width=True)
    else:
        st.warning("Najpierw wybierz działkę.")
