import streamlit as st
import httpx
import re
import ezdxf
from ezdxf import zoom
from pyproj import Transformer
import io
import folium
from streamlit_folium import st_folium
import zipfile  # Nowa biblioteka do tworzenia paczek ZIP

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

# 2. Funkcja: Wybór odpowiedniego układu 2000


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

if 'selected_id' not in st.session_state:
    st.session_state['selected_id'] = ""

tab1, tab2 = st.tabs(["📍 Wybierz z mapy", "⌨️ Wpisz ręcznie"])

with tab1:
    st.info("Przybliż mapę i kliknij w działkę.")
    m = folium.Map(location=[52.0, 19.0], zoom_start=6)
    folium.WmsTileLayer(
        url="https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardFull",
        layers="Raster", name="Ortofotomapa", fmt="image/png", transparent=True, overlay=False
    ).add_to(m)
    folium.WmsTileLayer(
        url="https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow",
        layers="dzialki", name="Działki", fmt="image/png", transparent=True, overlay=True
    ).add_to(m)

    output = st_folium(m, width="100%", height=500)

    if output and output.get("last_clicked"):
        lat, lon = output["last_clicked"]["lat"], output["last_clicked"]["lng"]
        with st.spinner("Identyfikowanie..."):
            found_id = get_id_by_xy(lon, lat)
            if found_id:
                st.session_state['selected_id'] = found_id
                st.success(f"Wybrana działka: {found_id}")

with tab2:
    input_id = st.text_input("Identyfikator działki",
                             value=st.session_state['selected_id'])
    if input_id:
        st.session_state['selected_id'] = input_id

# --- GENEROWANIE DANYCH ---
final_id = st.session_state['selected_id']

if st.button("🚀 Przygotuj pliki do pobrania", use_container_width=True):
    if final_id:
        with st.spinner('Przetwarzanie danych...'):
            punkty, epsg_result = process_parcel(final_id)

            if punkty:
                # 1. Przygotowanie TXT (jako string)
                txt_content = f"ID: {final_id}\nUklad: {epsg_result}\nFormat: Nr. X(Polnocna) Y(Wschodnia)\n" + \
                    "-"*40 + "\n"
                for i, (e, n) in enumerate(punkty, start=1):
                    txt_content += f"{i}. {n:.2f} {e:.2f}\n"

                # 2. Przygotowanie DXF (jako bytes)
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

                # 3. Tworzenie Archiwum ZIP (Pobierz oba naraz)
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    zip_file.writestr(f"{final_id}.txt", txt_content)
                    zip_file.writestr(f"{final_id}.dxf", dxf_data)

                st.divider()
                st.subheader("Opcje pobierania:")

                # PRZYCISK GŁÓWNY (Wszystko w jednym)
                st.download_button(
                    label="📦 POBIERZ WSZYSTKO (ZIP)",
                    data=zip_buffer.getvalue(),
                    file_name=f"Geomex_{final_id}.zip",
                    mime="application/zip",
                    use_container_width=True
                )

                # PRZYCISKI ODDZIELNE
                col1, col2 = st.columns(2)
                with col1:
                    st.download_button(
                        label="📄 Pobierz tylko TXT",
                        data=txt_content,
                        file_name=f"{final_id}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
                with col2:
                    st.download_button(
                        label="📐 Pobierz tylko DXF",
                        data=dxf_data,
                        file_name=f"{final_id}.dxf",
                        mime="application/dxf",
                        use_container_width=True
                    )
            else:
                st.error("Błąd przetwarzania.")
    else:
        st.warning("Najpierw wybierz działkę.")
