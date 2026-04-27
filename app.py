import streamlit as st
import httpx
import re
import ezdxf
from ezdxf import zoom
from pyproj import Transformer
import io


def get_epsg_2000(x_1992, y_1992):
    to_wgs84 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
    lon, lat = to_wgs84.transform(x_1992, y_1992)
    if lon < 16.5: return "EPSG:2176"
    elif lon < 19.5: return "EPSG:2177"
    elif lon < 22.5: return "EPSG:2178"
    else: return "EPSG:2179"

def process_parcel(identyfikator):
    url = f"https://uldk.gugik.gov.pl/?request=GetParcelById&id={identyfikator}&result=geom_wkt"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    response = httpx.get(url, headers=headers, timeout=20.0)
    wynik = response.text.strip().splitlines()
    
    if not wynik or wynik[0] != "0":
        return None, "Nie znaleziono działki lub błąd serwera."
    
    wkt = wynik[1]
    coords_raw = re.findall(r"([-+]?\d*\.\d+|\d+)\s+([-+]?\d*\.\d+|\d+)", wkt)
    
    x1, y1 = float(coords_raw[0][0]), float(coords_raw[0][1])
    target_epsg = get_epsg_2000(x1, y1)
    transformer = Transformer.from_crs("EPSG:2180", target_epsg, always_xy=True)

    points_2000 = []
    for x_92, y_92 in coords_raw:
        east, north = transformer.transform(float(x_92), float(y_92))
        points_2000.append((east, north)) # CAD (X=East, Y=North)
        
    return points_2000, target_epsg

# --- INTERFEJS UŻYTKOWNIKA (Streamlit) ---

st.set_page_config(page_title="Pobieracz Działek DXF", page_icon="🗺️")
st.title("🗺️ Pobieracz Współrzędnych i DXF")
st.write("Wpisz identyfikator działki, aby pobrać dane w układzie 2000.")

identyfikator = st.text_input("Identyfikator działki (np. 143407_2.0005.20)", "")

if st.button("Pobierz i przelicz"):
    if identyfikator:
        with st.spinner('Pobieranie danych z GUGiK...'):
            punkty, epsg = process_parcel(identyfikator)
            
            if punkty:
                st.success(f"Znaleziono działkę! Układ: {epsg}")
                
                # 1. Przygotowanie TXT
                txt_output = f"ID: {identyfikator}\nUklad: {epsg}\nFormat: Nr. X(Polnocna) Y(Wschodnia)\n" + "-"*40 + "\n"
                for i, (e, n) in enumerate(punkty, start=1):
                    txt_output += f"{i}. {n:.2f} {e:.2f}\n"
                
                # 2. Przygotowanie DXF w pamięci
                doc = ezdxf.new('R2010')    
                msp = doc.modelspace()
                msp.add_lwpolyline(punkty, close=True, dxfattribs={'color': 1})
                for i, (e, n) in enumerate(punkty, start=1):
                    msp.add_text(str(i), dxfattribs={'height': 0.8}).set_placement((e+0.5, n+0.5))
                zoom.extents(msp)
                
                dxf_stream = io.StringIO()
                doc.write(dxf_stream)
                
                # --- PRZYCISKI POBIERANIA ---
                col1, col2 = st.columns(2)
                
                with col1:
                    st.download_button(
                        label="Pobierz Plik TXT",
                        data=txt_output,
                        file_name=f"dzialka_{identyfikator}.txt",
                        mime="text/plain"
                    )
                
                with col2:
                    st.download_button(
                        label="Pobierz Plik DXF",
                        data=dxf_stream.getvalue(),
                        file_name=f"dzialka_{identyfikator}.dxf",
                        mime="application/dxf"
                    )
            else:
                st.error("Błąd: Nie udało się pobrać danych. Sprawdź identyfikator.")
    else:
        st.warning("Proszę wpisać identyfikator.")