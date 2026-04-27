import streamlit as st
import httpx
import re
import ezdxf
from ezdxf import zoom
from pyproj import Transformer
import io
import folium
from streamlit_folium import st_folium

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Geomex", page_icon="🗺️", layout="wide")

# 1. Funkcja: Pobieranie ID działki na podstawie kliknięcia (XY)


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

# 2. Funkcja: Wybór odpowiedniego układu 2000 (strefy 5, 6, 7 lub 8)


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

# 3. Funkcja: Pobieranie geometrii i konwersja


def process_parcel(identyfikator):
    url = f"https://uldk.gugik.gov.pl/?request=GetParcelById&id={identyfikator}&result=geom_wkt"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = httpx.get(url, headers=headers, timeout=20.0)
        wynik = response.text.strip().splitlines()
        if not wynik or wynik[0] != "0":
            return None, "Nie znaleziono działki."

        wkt = wynik[1]
        coords_raw = re.findall(
            r"([-+]?\d*\.\d+|\d+)\s+([-+]?\d*\.\d+|\d+)", wkt)

        if not coords_raw:
            return None, "Błąd odczytu geometrii."

        # Pierwszy punkt do ustalenia strefy EPSG
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
st.title("🗺️ Geomex - Interaktywna Mapa Działek")

# Inicjalizacja stanu dla ID, jeśli jeszcze nie istnieje
if 'selected_id' not in st.session_state:
    st.session_state['selected_id'] = ""

tab1, tab2 = st.tabs(["📍 Wybierz z mapy", "⌨️ Wpisz ręcznie"])

with tab1:
    st.info("Przybliż mapę i kliknij w środek działki, aby pobrać jej numer.")

    # Mapa startuje na środku Polski
    m = folium.Map(location=[52.0, 19.0], zoom_start=6)

    # Dodanie Ortofotomapy (warstwa zdjęć satelitarnych)
    folium.WmsTileLayer(
        url="https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardFull",
        layers="Raster",
        name="Ortofotomapa",
        fmt="image/png",
        transparent=True,
        overlay=False
    ).add_to(m)

    # Dodanie warstwy Działek (KIEG)
    folium.WmsTileLayer(
        url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
        layers="dzialki",
        name="Działki",
        fmt="image/png",
        transparent=True,
        overlay=True
    ).add_to(m)

    # Wyświetlenie mapy
    output = st_folium(m, width="100%", height=600)

    # Obsługa kliknięcia
    if output and output.get("last_clicked"):
        lat = output["last_clicked"]["lat"]
        lon = output["last_clicked"]["lng"]

        with st.spinner("Identyfikowanie działki..."):
            found_id = get_id_by_xy(lon, lat)
            if found_id:
                st.session_state['selected_id'] = found_id
                st.success(f"Wybrana działka: {found_id}")
            else:
                st.error("Nie znaleziono działki w tym miejscu.")

with tab2:
    input_id = st.text_input(
        "Wpisz identyfikator działki", value=st.session_state['selected_id'])
    if input_id:
        st.session_state['selected_id'] = input_id

# --- GENEROWANIE PLIKÓW ---
final_id = st.session_state['selected_id']

if st.button("🚀 Generuj dane dla działki", use_container_width=True):
    if final_id:
        with st.spinner('Pobieranie i przeliczanie współrzędnych...'):
            punkty, epsg_result = process_parcel(final_id)

            if punkty:
                st.balloons()

                # Przygotowanie TXT
                txt_output = f"ID: {final_id}\nUklad: {epsg_result}\nFormat: Nr. X(Polnocna) Y(Wschodnia)\n" + \
                    "-"*40 + "\n"
                for i, (e, n) in enumerate(punkty, start=1):
                    txt_output += f"{i}. {n:.2f} {e:.2f}\n"

                # Przygotowanie DXF
                doc = ezdxf.new('R2010')
                msp = doc.modelspace()
                msp.add_lwpolyline(punkty, close=True, dxfattribs={'color': 1})
                for i, (e, n) in enumerate(punkty, start=1):
                    msp.add_text(str(i), dxfattribs={'height': 0.8}).set_placement(
                        (e+0.5, n+0.5))
                zoom.extents(msp)
                dxf_stream = io.StringIO()
                doc.write(dxf_stream)

                # Przyciski
                c1, c2 = st.columns(2)
                c1.download_button("📄 Pobierz TXT", data=txt_output,
                                   file_name=f"{final_id}.txt", use_container_width=True)
                c2.download_button("📐 Pobierz DXF", data=dxf_stream.getvalue(
                ), file_name=f"{final_id}.dxf", use_container_width=True)
            else:
                st.error(f"Coś poszło nie tak: {epsg_result}")
    else:
        st.warning("Najpierw wybierz działkę z mapy lub wpisz jej numer.")
