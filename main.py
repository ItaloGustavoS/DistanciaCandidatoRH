import datetime
import os
import time
import json
import streamlit as st
import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import gspread
import pandas as pd
import folium
from streamlit_folium import st_folium

# --- Configurações ---
# API pública do OSRM
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/driving/"
# User-Agent para o Nominatim
NOMINATIM_USER_AGENT = "minha-aplicacao-lojas-streamlit-v4"  # Alterado para v4

# Nome do arquivo JSON com as credenciais do Google Sheets
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"
# Nome da sua planilha do Google Sheets
GOOGLE_SHEET_NAME = "Dados Candidatos Lojas"

# --- Seus 7 endereços de lojas ---
enderecos_lojas = {
    "Loja Centro": "Rua dos Tamoios, 300, Centro, Belo Horizonte, MG, Brasil",
    "Loja Savassi": "Rua Pernambuco, 1000, Savassi, Belo Horizonte, MG, Brasil",
    "Loja Pampulha": "Avenida Otacílio Negrão de Lima, 6000, Pampulha, Belo Horizonte, MG, Brasil",
    "Loja Contagem": "Avenida João César de Oliveira, 200, Eldorado, Contagem, MG, Brasil",
    "Loja Betim": "Rua do Rosário, 150, Centro, Betim, MG, Brasil",
    "Loja Vespasiano": "Avenida Thales Chagas, 50, Centro, Vespasiano, MG, Brasil",
    "Loja Nova Lima": "Alameda Oscar Niemeyer, 500, Vale do Sereno, Nova Lima, MG, Brasil",
}

# --- Funções de Geocodificação e OSRM (com cache) ---


@st.cache_data(ttl=3600)
def geocodificar_endereco(endereco):
    geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT)
    try:
        location = geolocator.geocode(endereco, timeout=10)
        if location:
            st.info(
                f"Endereço '{endereco}' geocodificado para: ({location.latitude:.4f}, {location.longitude:.4f})"
            )
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
                st.warning(
                    f"AVISO OSRM: Dados de rota incompletos ou ausentes entre ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) e ({coord_destino[0]:.4f}, {coord_destino[1]:.4f})."
                )
                return None, None, None
        else:
            st.warning(
                f"AVISO OSRM: Nenhuma rota encontrada entre os pontos: ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) e ({coord_destino[0]:.4f}, {coord_destino[1]:.4f})."
            )
            return None, None, None
    except requests.exceptions.RequestException as e:
        st.error(
            f"ERRO de requisição OSRM entre ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) e ({coord_destino[0]:.4f}, {coord_destino[1]:.4f}): {e}. O serviço pode estar indisponível ou você atingiu o limite de requisições."
        )
        return None, None, None


# --- Funções para Interagir com Google Sheets ---


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
            f"Planilha '{GOOGLE_SHEET_NAME}' não encontrada ao autenticar. Verifique o nome da planilha e se ela está compartilhada com o e-mail da conta de serviço."
        )
        return None
    except Exception as e:
        st.error(
            f"Erro inesperado ao autenticar no Google Sheets: {e}. Verifique suas credenciais e o formato do secret TOML."
        )
        return None


@st.cache_data(ttl=60)
def carregar_dados_candidatos():
    gc = get_google_sheet_client()
    if gc is None:
        return pd.DataFrame()

    try:
        sh = gc.open(GOOGLE_SHEET_NAME)
        worksheet = sh.sheet1
        dados = worksheet.get_all_records()
        df = pd.DataFrame(dados)
        return df
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(
            f"Erro: Planilha '{GOOGLE_SHEET_NAME}' não encontrada. Verifique o nome e compartilhamento."
        )
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar dados do Google Sheets: {e}.")
        return pd.DataFrame()


def adicionar_candidato(nome, endereco, loja_mais_proxima, distancia, tempo):
    gc = get_google_sheet_client()
    if gc is None:
        return False
    try:
        sh = gc.open(GOOGLE_SHEET_NAME)
        worksheet = sh.sheet1
        data_hora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        nova_linha = [
            nome,
            endereco,
            loja_mais_proxima,
            f"{distancia:.2f}",
            f"{tempo:.1f}",
            data_hora,
        ]
        worksheet.append_row(nova_linha)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Erro ao adicionar candidato no Google Sheets: {e}")
        return False


def limpar_dados_candidatos():
    gc = get_google_sheet_client()
    if gc is None:
        return False
    try:
        sh = gc.open(GOOGLE_SHEET_NAME)
        worksheet = sh.sheet1
        all_values = worksheet.get_all_values()
        if len(all_values) > 1:
            worksheet.delete_rows(2, len(all_values))
            st.cache_data.clear()
            st.success("Dados do histórico apagados com sucesso!")
            return True
        else:
            st.info("Não há dados para apagar no histórico.")
            return False
    except Exception as e:
        st.error(f"Erro ao limpar dados do Google Sheets: {e}")
        return False


# --- Nova Função para Gerar o Mapa do Histórico ---
def gerar_mapa_historico(df_historico, enderecos_lojas_dict):
    if df_historico.empty:
        st.warning("Não há dados no histórico para gerar o mapa.")
        return

    # Inicia o mapa centrado em BH ou na primeira coordenada válida encontrada
    map_center = [-19.919, -43.938]  # Default para BH

    # Lista para armazenar todas as coordenadas para o ajuste do zoom
    all_coords_on_map = []

    m = folium.Map(location=map_center, zoom_start=12)

    # Adicionar marcadores das lojas
    lojas_coordenadas_cache = {}
    for nome_loja, endereco_completo in enderecos_lojas_dict.items():
        coords_loja = geocodificar_endereco(endereco_completo)
        if coords_loja:
            lojas_coordenadas_cache[nome_loja] = coords_loja
            folium.Marker(
                [coords_loja[0], coords_loja[1]],
                tooltip=f"Loja: {nome_loja}<br>Endereço: {endereco_completo}<br>Coordenadas: ({coords_loja[0]:.4f}, {coords_loja[1]:.4f})",
                icon=folium.Icon(color="red", icon="store", prefix="fa"),
            ).add_to(m)
            all_coords_on_map.append(coords_loja)

    # Adicionar marcadores dos candidatos
    for index, row in df_historico.iterrows():
        nome = row["Nome"]
        endereco = row["Endereço"]
        loja_mais_proxima = row["Loja Mais Próxima"]

        coords_candidato = geocodificar_endereco(endereco)
        if coords_candidato:
            folium.Marker(
                [coords_candidato[0], coords_candidato[1]],
                tooltip=f"Candidato: {nome}<br>Endereço: {endereco}<br>Loja Mais Próxima: {loja_mais_proxima}<br>Coordenadas: ({coords_candidato[0]:.4f}, {coords_candidato[1]:.4f})",
                icon=folium.Icon(color="blue", icon="user", prefix="fa"),
            ).add_to(m)
            all_coords_on_map.append(coords_candidato)

            # Opcional: Desenhar rota do candidato para a loja mais próxima (pode ser lento se muitos candidatos)
            if loja_mais_proxima in lojas_coordenadas_cache:
                coords_loja_selecionada = lojas_coordenadas_cache[loja_mais_proxima]
                # A função obter_distancia_osrm precisa de otimização para não recarregar toda vez
                # e também cuidado com o limite de requests para muitos pontos.
                # Para este mapa, vamos tentar buscar a rota, mas esteja ciente das limitações
                dist_km, tempo_seg, geometry = obter_distancia_osrm(
                    coords_candidato, coords_loja_selecionada
                )
                if geometry:
                    inverted_coordinates = [
                        [coord[1], coord[0]] for coord in geometry["coordinates"]
                    ]
                    folium.PolyLine(
                        inverted_coordinates,
                        color="purple",  # Cor diferente para rotas históricas
                        weight=3,
                        opacity=0.5,
                        tooltip=f"Rota para {loja_mais_proxima}: {dist_km:.2f} km",
                    ).add_to(m)
                time.sleep(
                    0.1
                )  # Pequena pausa entre cada rota para evitar hitting API limits
        time.sleep(0.1)  # Pequena pausa entre cada candidato geocodificado

    # Ajusta o mapa para mostrar todos os pontos adicionados
    if all_coords_on_map:
        m.fit_bounds(
            [
                [
                    min(p[0] for p in all_coords_on_map),
                    min(p[1] for p in all_coords_on_map),
                ],
                [
                    max(p[0] for p in all_coords_on_map),
                    max(p[1] for p in all_coords_on_map),
                ],
            ]
        )

    st_folium(m, width=700, height=500)


# --- Interface Streamlit ---
st.set_page_config(
    page_title="Localizador de Loja Mais Próxima", page_icon="📍", layout="wide"
)

st.title("📍 Localizador de Loja Mais Próxima")
st.write(
    "Insira o nome e endereço do candidato para encontrar a loja mais próxima e registrar os dados."
)

# --- Entrada de Dados do Candidato ---
with st.container():
    st.header("Dados do Candidato")
    col1, col2 = st.columns([1, 2])
    with col1:
        nome_candidato_input = st.text_input(
            "Nome do Candidato", placeholder="João da Silva"
        )
    with col2:
        endereco_candidato_input = st.text_input(
            "Endereço do Candidato (Ex: Avenida Afonso Pena, 1000, Centro, Belo Horizonte, MG, Brasil)",
            placeholder="Digite o endereço completo como o do exemplo aqui...",
        )

    if st.button("Encontrar Loja e Registrar"):
        if not nome_candidato_input or not endereco_candidato_input:
            st.warning("Por favor, preencha o nome e o endereço do candidato.")
        else:
            with st.spinner(
                "Calculando a loja mais próxima e registrando... Isso pode levar alguns segundos."
            ):
                coords_candidato = geocodificar_endereco(endereco_candidato_input)

                if not coords_candidato:
                    st.error(
                        "Não foi possível processar o endereço do candidato. A geocodificação falhou. Por favor, revise o endereço e tente novamente."
                    )
                else:
                    st.markdown(
                        f"**Coordenadas do Candidato:** Latitude: **{coords_candidato[0]:.6f}**, Longitude: **{coords_candidato[1]:.6f}**"
                    )

                    coords_lojas = {}
                    for nome_loja, endereco_completo in enderecos_lojas.items():
                        coords = geocodificar_endereco(endereco_completo)
                        if coords:
                            coords_lojas[nome_loja] = coords
                        time.sleep(0.5)  # Pausa para Nominatim

                    if not coords_lojas:
                        st.error(
                            "Nenhuma das lojas pôde ser geocodificada. Verifique os endereços pré-definidos das lojas."
                        )
                    else:
                        st.markdown("---")
                        st.subheader("Coordenadas das Lojas Geocodificadas:")
                        for nome_loja, coords in coords_lojas.items():
                            st.write(
                                f"- **{nome_loja}**: Latitude: **{coords[0]:.6f}**, Longitude: **{coords[1]:.6f}**"
                            )
                        st.markdown("---")

                        melhor_distancia_km = float("inf")
                        melhor_tempo_seg = float("inf")
                        loja_mais_proxima = None

                        progress_bar = st.progress(0)

                        for i, (nome_loja, coords_loja) in enumerate(
                            coords_lojas.items()
                        ):
                            dist_km, tempo_seg, _ = (
                                obter_distancia_osrm(  # Não precisamos da geometria aqui
                                    coords_candidato, coords_loja
                                )
                            )

                            if dist_km is not None and tempo_seg is not None:
                                if dist_km < melhor_distancia_km:
                                    melhor_distancia_km = dist_km
                                    melhor_tempo_seg = tempo_seg
                                    loja_mais_proxima = nome_loja
                            time.sleep(0.5)  # Pausa para OSRM
                            progress_bar.progress((i + 1) / len(coords_lojas))

                        if loja_mais_proxima:
                            st.success("--- Resultado da Busca ---")
                            st.markdown(f"**Candidato:** {nome_candidato_input}")
                            st.markdown(f"**Endereço:** {endereco_candidato_input}")
                            st.markdown(
                                f"A loja mais próxima é: **{loja_mais_proxima}**."
                            )
                            st.markdown(
                                f"Distância da rota: **{melhor_distancia_km:.2f} km**."
                            )
                            st.markdown(
                                f"Tempo de viagem estimado: **{melhor_tempo_seg / 60:.1f} minutos**."
                            )

                            # Adicionar ao Google Sheets
                            if adicionar_candidato(
                                nome_candidato_input,
                                endereco_candidato_input,
                                loja_mais_proxima,
                                melhor_distancia_km,
                                melhor_tempo_seg / 60,
                            ):
                                st.success(
                                    "Dados do candidato registrados com sucesso no Google Sheets!"
                                )
                                st.session_state["data_updated"] = True
                            else:
                                st.error("Falha ao registrar dados no Google Sheets.")
                        else:
                            st.error(
                                "Não foi possível determinar a loja mais próxima. Verifique os endereços informados, os serviços de geocodificação (Nominatim) e de rota (OSRM) e tente novamente."
                            )

# --- Histórico de Candidatos ---
st.markdown("---")
st.header("📊 Histórico de Candidatos")

# Botões de controle para o histórico e mapa
col_hist1, col_hist2, col_hist3 = st.columns([1, 1, 3])
with col_hist1:
    if st.button("Atualizar Histórico"):
        st.cache_data.clear()
        st.session_state["data_updated"] = True
with col_hist2:
    if st.button(
        "Limpar Histórico de Candidatos",
        help="Isso apagará TODOS os dados no Google Sheets para esta aplicação.",
    ):
        if limpar_dados_candidatos():
            st.session_state["data_updated"] = True
            st.session_state["show_map"] = False  # Esconde o mapa após limpar
with col_hist3:
    if st.button("Gerar Mapa Histórico"):
        st.session_state["show_map"] = True  # Define uma flag para exibir o mapa

dados_historico = carregar_dados_candidatos()

if not dados_historico.empty:
    st.dataframe(dados_historico, use_container_width=True)
else:
    st.info(
        "Nenhum dado de candidato encontrado no histórico. Faça uma pesquisa acima para começar."
    )

# --- Exibição Condicional do Mapa ---
if "show_map" not in st.session_state:
    st.session_state["show_map"] = False

if st.session_state["show_map"]:
    st.markdown("---")
    st.subheader("🌍 Mapa do Histórico de Candidatos e Lojas")
    with st.spinner("Gerando mapa com todos os pontos..."):
        gerar_mapa_historico(dados_historico, enderecos_lojas)
    st.markdown("---")


st.markdown("Desenvolvido com ❤️ e Streamlit")
