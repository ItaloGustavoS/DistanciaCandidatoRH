import datetime
import os
import time
import json
import streamlit as st
import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import folium
from streamlit_folium import st_folium
import pytz
import gspread

# --- Configurações ---
# API pública do OSRM
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/driving/"
# User-Agent para o Nominatim
NOMINATIM_USER_AGENT = "minha-aplicacao-lojas-streamlit-v11"  # Versão atualizada

# Nome do arquivo JSON com as credenciais do Google Sheets
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"
# Nome da sua planilha do Google Sheets para o LOG (pode ser a mesma ou uma nova)
GOOGLE_LOG_SHEET_NAME = (
    "Log Pesquisas Lojas"  # Mantenha este nome consistente com sua planilha
)

# Fuso horário de Brasília
BRAZIL_TIMEZONE = pytz.timezone("America/Sao_Paulo")

# --- Seus 7 endereços de lojas ---
enderecos_lojas = {
    "Loja Lourdes": "Rua Marília de Dirceu, 161, Lourdes, Belo Horizonte, MG, Brasil",
    "Loja Anchieta": "Avenida dos Bandeirantes, 1733, Anchieta, Belo Horizonte, MG, Brasil",
    "Loja Savassi": "Rua Lavras, 96, Savassi, Belo Horizonte, MG, Brasil",
    "Loja Vila da Serra - Oscar Niemeyer": "Alameda Oscar Niemeyer, 1033, Vila da Serra, Nova Lima, MG, Brasil",
    "Loja Santo Agostinho": "Avenida Olegário Maciel, 1600, Santo Agostinho, Belo Horizonte, MG, Brasil",
    "Loja Vila da Serra - Dicíola": "R. Dicíola Horta, 77, Vila da Serra, Belo Horizonte, MG, Brasil",
    "Loja Belvedere": "BR 356, 3049, Belvedere, Belo Horizonte, MG, Brasil",
}

# --- Funções de Geocodificação e OSRM (com cache) ---


@st.cache_data(ttl=3600)
def geocodificar_endereco(endereco):
    geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT)
    try:
        location = geolocator.geocode(endereco, timeout=10)
        if location:
            return location.latitude, location.longitude
        st.warning(
            f"Não foi possível geocodificar: '{endereco}'. Verifique a digitação ou tente um endereço mais completo (com cidade, estado e país)."
        )
        return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        st.error(
            f"Erro de geocodificação para '{endereco}': {e}. Tente novamente mais tarde ou verifique sua conexão."
        )
        return None


@st.cache_data(ttl=3600)
def obter_distancia_osrm(coord_origem, coord_destino):
    if not coord_origem or not coord_destino:
        return None, None, None

    url = f"{OSRM_BASE_URL}{coord_origem[1]},{coord_origem[0]};{coord_destino[1]},{coord_destino[0]}?overview=full&steps=true&geometries=geojson"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data and "routes" in data and len(data["routes"]) > 0:
            route_info = data["routes"][0]
            distance_meters = route_info.get("distance")
            duration_seconds = route_info.get("duration")
            geometry = route_info.get("geometry")

            if (
                distance_meters is not None
                and duration_seconds is not None
                and geometry is not None
            ):
                return distance_meters / 1000, duration_seconds, geometry
            else:
                msg = f"AVISO OSRM: Dados de rota incompletos ou ausentes entre ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) e ({coord_destino[0]:.4f}, {coord_destino[1]:.4f})."
                st.warning(msg)
                return None, None, None
        else:
            msg = f"AVISO OSRM: Nenhuma rota encontrada entre os pontos: ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) e ({coord_destino[0]:.4f}, {coord_destino[1]:.4f})."
            st.warning(msg)
            return None, None, None
    except requests.exceptions.RequestException as e:
        msg = f"ERRO de requisição OSRM entre ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) e ({coord_destino[0]:.4f}, {coord_destino[1]:.4f}): {e}. O serviço pode estar indisponível ou você atingiu o limite de requisições."
        st.error(msg)
        return None, None, None


# --- Funções para Interagir com Google Sheets (para Log) ---


@st.cache_resource
def get_google_sheet_client():
    try:
        if "GSPREAD_SERVICE_ACCOUNT_JSON" in st.secrets:
            credentials_json_str = st.secrets["GSPREAD_SERVICE_ACCOUNT_JSON"]
            gc = gspread.service_account_from_dict(json.loads(credentials_json_str))
        elif os.path.exists(GOOGLE_CREDENTIALS_FILE):
            gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
        else:
            st.error(
                f"Erro: Arquivo de credenciais '{GOOGLE_CREDENTIALS_FILE}' não encontrado "
                "e secret 'GSPREAD_SERVICE_ACCOUNT_JSON' não configurado. Por favor, siga as instruções de configuração."
            )
            return None
        return gc
    except gspread.exceptions.APIError as e:
        st.error(
            f"Erro de API ao autenticar no Google Sheets: {e}. Verifique suas credenciais e habilite as APIs necessárias (Sheets e Drive)."
        )
        return None
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(
            f"Planilha '{GOOGLE_LOG_SHEET_NAME}' não encontrada ao autenticar. Verifique o nome da planilha e se ela está compartilhada com o e-mail da conta de serviço."
        )
        return None
    except Exception as e:
        st.error(
            f"Erro inesperado ao autenticar no Google Sheets: {e}. Verifique suas credenciais e o formato do secret TOML."
        )
        return None


def adicionar_log(endereco_pesquisado, status, mensagem_log=""):
    gc = get_google_sheet_client()
    if gc is None:
        st.warning(
            "Não foi possível adicionar o log: Cliente do Google Sheets não disponível."
        )
        return False
    try:
        sh = gc.open(GOOGLE_LOG_SHEET_NAME)
        worksheet = sh.sheet1  # Assume que o log vai para a primeira aba

        # Obtém a hora atual no fuso horário de Brasília
        now_utc = datetime.datetime.now(pytz.utc)
        now_br = now_utc.astimezone(BRAZIL_TIMEZONE)
        data_hora_br = now_br.strftime("%d/%m/%Y %H:%M")  # Formato de exibição

        nova_linha = [data_hora_br, endereco_pesquisado, status, mensagem_log]
        worksheet.append_row(nova_linha)
        return True
    except Exception as e:
        st.error(f"Erro ao adicionar log no Google Sheets: {e}")
        return False


# --- Funções para Gerar o Mapa ---
def gerar_mapa_pesquisa(
    coords_candidato,
    endereco_candidato,
    loja_mais_proxima_nome,
    coords_loja_mais_proxima,
    endereco_loja_mais_proxima,
    geometry_route,
):
    map_center = coords_candidato if coords_candidato else [-19.919, -43.938]
    m = folium.Map(location=map_center, zoom_start=12)

    if coords_candidato:
        folium.Marker(
            [coords_candidato[0], coords_candidato[1]],
            tooltip=f"Origem: {endereco_candidato}<br>Coordenadas: ({coords_candidato[0]:.4f}, {coords_candidato[1]:.4f})",
            icon=folium.Icon(color="blue", icon="user", prefix="fa"),
        ).add_to(m)

    if coords_loja_mais_proxima:
        folium.Marker(
            [coords_loja_mais_proxima[0], coords_loja_mais_proxima[1]],
            tooltip=f"Loja: {loja_mais_proxima_nome}<br>Endereço: {endereco_loja_mais_proxima}<br>Coordenadas: ({coords_loja_mais_proxima[0]:.4f}, {coords_loja_mais_proxima[1]:.4f})",
            icon=folium.Icon(color="red", icon="store", prefix="fa"),
        ).add_to(m)

    if geometry_route:
        inverted_coordinates = [
            [coord[1], coord[0]] for coord in geometry_route["coordinates"]
        ]
        folium.PolyLine(
            inverted_coordinates,
            color="purple",
            weight=3,
            opacity=0.7,
            tooltip=f"Rota entre Candidato e {loja_mais_proxima_nome}",
        ).add_to(m)

    all_coords_on_map = []
    if coords_candidato:
        all_coords_on_map.append(coords_candidato)
    if coords_loja_mais_proxima:
        all_coords_on_map.append(coords_loja_mais_proxima)

    if len(all_coords_on_map) == 2:
        min_lat = min(p[0] for p in all_coords_on_map)
        max_lat = max(p[0] for p in all_coords_on_map)
        min_lon = min(p[1] for p in all_coords_on_map)
        max_lon = max(p[1] for p in all_coords_on_map)
        m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])
    elif len(all_coords_on_map) == 1:
        m.location = all_coords_on_map[0]
        m.zoom_start = 14

    st_folium(m, width=700, height=500)


# --- Interface Streamlit ---
st.set_page_config(
    page_title="Localizador de Loja Mais Próxima", page_icon="📍", layout="wide"
)

st.title("📍 Localizador de Loja Mais Próxima")
st.write("Insira o endereço para encontrar a loja mais próxima.")

# --- Entrada de Dados ---
with st.container():
    st.header("Endereço para Pesquisa")
    endereco_candidato_input = st.text_input(
        "Endereço (Ex: Avenida Afonso Pena, 1000, Centro, Belo Horizonte, MG, Brasil)",
        placeholder="Digite o endereço completo como o do exemplo aqui...",
        key="address_input",
    )

    # Use st.session_state para armazenar os resultados e exibi-los
    if "results_displayed" not in st.session_state:
        st.session_state["results_displayed"] = False
        st.session_state["loja_mais_proxima_data"] = (
            None  # Para guardar os dados da pesquisa
        )

    if st.button("Encontrar Loja"):
        st.session_state["results_displayed"] = False  # Resetar para nova pesquisa
        st.session_state["loja_mais_proxima_data"] = None

        if not endereco_candidato_input:
            st.warning("Por favor, preencha o endereço para pesquisa.")
            adicionar_log(endereco_candidato_input, "ERRO", "Endereço não preenchido.")
        else:
            with st.spinner(
                "Calculando a loja mais próxima... Isso pode levar alguns segundos."
            ):
                coords_candidato = geocodificar_endereco(endereco_candidato_input)

                if not coords_candidato:
                    error_msg = f"Não foi possível processar o endereço. A geocodificação falhou para '{endereco_candidato_input}'."
                    st.error(error_msg)
                    adicionar_log(endereco_candidato_input, "ERRO", error_msg)
                else:
                    coords_lojas = {}
                    for nome_loja, endereco_completo in enderecos_lojas.items():
                        coords = geocodificar_endereco(endereco_completo)
                        if coords:
                            coords_lojas[nome_loja] = coords
                        time.sleep(0.6)  # AJUSTADO PARA 0.6 SEGUNDOS

                    if not coords_lojas:
                        error_msg = "Nenhuma das lojas pôde ser geocodificada. Verifique os endereços pré-definidos das lojas."
                        st.error(error_msg)
                        adicionar_log(endereco_candidato_input, "ERRO", error_msg)
                    else:
                        melhor_distancia_km = float("inf")
                        melhor_tempo_seg = float("inf")
                        loja_mais_proxima_nome = None
                        endereco_loja_selecionada = None
                        coords_loja_selecionada = None
                        geometry_rota_selecionada = None

                        # Barra de progresso removida
                        # progress_bar = st.progress(0)

                        for i, (nome_loja, coords_loja) in enumerate(
                            coords_lojas.items()
                        ):
                            dist_km, tempo_seg, geometry = obter_distancia_osrm(
                                coords_candidato, coords_loja
                            )

                            if dist_km is not None and tempo_seg is not None:
                                if dist_km < melhor_distancia_km:
                                    melhor_distancia_km = dist_km
                                    melhor_tempo_seg = tempo_seg
                                    loja_mais_proxima_nome = nome_loja
                                    endereco_loja_selecionada = enderecos_lojas[
                                        nome_loja
                                    ]
                                    coords_loja_selecionada = coords_loja
                                    geometry_rota_selecionada = geometry
                            time.sleep(0.6)  # AJUSTADO PARA 0.6 SEGUNDOS
                            # progress_bar.progress((i + 1) / len(coords_lojas)) # Atualização da barra de progresso removida

                        if loja_mais_proxima_nome:
                            # Armazenar os dados na session_state
                            st.session_state["loja_mais_proxima_data"] = {
                                "endereco_pesquisado": endereco_candidato_input,
                                "coords_candidato": coords_candidato,
                                "loja_mais_proxima_nome": loja_mais_proxima_nome,
                                "endereco_loja_selecionada": endereco_loja_selecionada,
                                "coords_loja_selecionada": coords_loja_selecionada,
                                "melhor_distancia_km": melhor_distancia_km,
                                "melhor_tempo_seg": melhor_tempo_seg,
                                "geometry_rota_selecionada": geometry_rota_selecionada,
                            }
                            st.session_state["results_displayed"] = True
                            adicionar_log(
                                endereco_candidato_input,
                                "OK",
                                f"Loja encontrada: {loja_mais_proxima_nome}",
                            )

                        else:
                            error_msg = "Não foi possível determinar a loja mais próxima. Verifique o endereço informado ou a disponibilidade dos serviços."
                            st.error(error_msg)
                            adicionar_log(endereco_candidato_input, "ERRO", error_msg)

    # Exibir os resultados e o mapa se houver dados na session_state
    if (
        st.session_state["results_displayed"]
        and st.session_state["loja_mais_proxima_data"]
    ):
        data = st.session_state["loja_mais_proxima_data"]
        st.success("--- Resultado da Pesquisa ---")
        st.markdown(f"**Endereço Pesquisado:** {data['endereco_pesquisado']}")
        st.markdown(
            f"**Coordenadas:** Latitude: **{data['coords_candidato'][0]:.6f}**, Longitude: **{data['coords_candidato'][1]:.6f}**"
        )
        st.markdown(f"A loja mais próxima é: **{data['loja_mais_proxima_nome']}**.")
        st.markdown(
            f"Endereço da Loja Mais Próxima: **{data['endereco_loja_selecionada']}**."
        )
        st.markdown(f"Distância da rota: **{data['melhor_distancia_km']:.2f} km**.")
        st.markdown(
            f"Tempo de viagem estimado: **{data['melhor_tempo_seg'] / 60:.1f} minutos**."
        )

        st.markdown("---")
        st.subheader("🌍 Mapa da Rota")
        gerar_mapa_pesquisa(
            data["coords_candidato"],
            data["endereco_pesquisado"],
            data["loja_mais_proxima_nome"],
            data["coords_loja_selecionada"],
            data["endereco_loja_selecionada"],
            data["geometry_rota_selecionada"],
        )
        st.markdown("---")


st.markdown("Desenvolvido com ❤️ e Streamlit")
