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
# API pública do OSRM (lembre-se dos limites de uso!)
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/driving/"
# User-Agent para o Nominatim
NOMINATIM_USER_AGENT = "minha-aplicacao-lojas-streamlit-v2"  # Altere para um nome único

# Nome do arquivo JSON com as credenciais do Google Sheets
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"
# Nome da sua planilha do Google Sheets
GOOGLE_SHEET_NAME = "Dados Candidatos Lojas"  # Mude para o nome da sua planilha

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
            return location.latitude, location.longitude
        st.warning(
            f"Não foi possível geocodificar: '{endereco}'. Verifique a digitação."
        )
        return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        st.error(
            f"Erro de geocodificação para '{endereco}': {e}. Tente novamente mais tarde."
        )
        return None


@st.cache_data(ttl=3600)
def obter_distancia_osrm(coord_origem, coord_destino):
    if not coord_origem or not coord_destino:
        return None, None

    url = f"{OSRM_BASE_URL}{coord_origem[1]},{coord_origem[0]};{coord_destino[1]},{coord_destino[0]}?overview=false&steps=true&geometries=geojson"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data and "routes" in data and len(data["routes"]) > 0:
            route_info = data["routes"][0]
            distance_meters = route_info["distance"]
            duration_seconds = route_info["duration"]
            geometry = route_info["geometry"]  # Geometria da rota
            return distance_meters / 1000, duration_seconds, geometry
        else:
            st.warning(
                f"AVISO OSRM: Nenhuma rota encontrada entre os pontos. Verifique as coordenadas."
            )
            return None, None, None
    except requests.exceptions.RequestException as e:
        st.error(
            f"ERRO de requisição OSRM: {e}. O serviço pode estar indisponível ou você atingiu o limite de requisições."
        )
        return None, None, None


# --- Funções para Interagir com Google Sheets ---


# @st.cache_resource permite que a conexão gspread seja reutilizada
@st.cache_resource
def get_google_sheet_client():
    try:
        # Tenta carregar as credenciais do ambiente (para hospedagem segura)
        # ou do arquivo local
        if "GSPREAD_SERVICE_ACCOUNT_JSON" in os.environ:
            credentials_json = os.environ["GSPREAD_SERVICE_ACCOUNT_JSON"]
            gc = gspread.service_account_from_dict(json.loads(credentials_json))
        elif os.path.exists(GOOGLE_CREDENTIALS_FILE):
            gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
        else:
            st.error(
                f"Erro: Arquivo de credenciais '{GOOGLE_CREDENTIALS_FILE}' não encontrado "
                "e variável de ambiente 'GSPREAD_SERVICE_ACCOUNT_JSON' não configurada."
            )
            return None
        return gc
    except Exception as e:
        st.error(
            f"Erro ao autenticar no Google Sheets: {e}. Verifique suas credenciais."
        )
        return None


@st.cache_data(ttl=60)  # Cacheia o DataFrame por 60 segundos
def carregar_dados_candidatos():
    gc = get_google_sheet_client()
    if gc is None:
        return pd.DataFrame()  # Retorna DataFrame vazio em caso de erro

    try:
        sh = gc.open(GOOGLE_SHEET_NAME)
        worksheet = sh.sheet1  # Pega a primeira aba
        dados = (
            worksheet.get_all_records()
        )  # Obtém todos os dados como lista de dicionários
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
        st.cache_data.clear()  # Limpa o cache para recarregar os dados
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
        # Obtém todos os valores para verificar se há algo além dos cabeçalhos
        all_values = worksheet.get_all_values()
        if len(all_values) > 1:  # Se há mais de uma linha (cabeçalho + dados)
            worksheet.delete_rows(
                2, len(all_values)
            )  # Apaga todas as linhas a partir da segunda
            st.cache_data.clear()  # Limpa o cache
            st.success("Dados do histórico apagados com sucesso!")
            return True
        else:
            st.info("Não há dados para apagar no histórico.")
            return False
    except Exception as e:
        st.error(f"Erro ao limpar dados do Google Sheets: {e}")
        return False


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
            "Endereço do Candidato (Ex: Rua da Paz, 20, Belo Horizonte, MG, Brasil)",
            placeholder="Digite o endereço completo aqui...",
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
                        "Não foi possível processar o endereço do candidato. Tente novamente."
                    )
                else:
                    coords_lojas = {}
                    for nome_loja, endereco_completo in enderecos_lojas.items():
                        coords = geocodificar_endereco(endereco_completo)
                        if coords:
                            coords_lojas[nome_loja] = coords
                        time.sleep(0.1)  # Pequena pausa para Nominatim

                    if not coords_lojas:
                        st.error(
                            "Nenhuma das lojas pôde ser geocodificada. Verifique os endereços pré-definidos."
                        )
                    else:
                        melhor_distancia_km = float("inf")
                        melhor_tempo_seg = float("inf")
                        loja_mais_proxima = None
                        geometria_rota_mais_curta = None

                        progress_bar = st.progress(0)
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
                                    loja_mais_proxima = nome_loja
                                    geometria_rota_mais_curta = (
                                        geometry  # Salva a geometria da rota mais curta
                                    )
                            time.sleep(0.1)  # Pequena pausa para OSRM
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
                            ):  # Tempo em minutos
                                st.success(
                                    "Dados do candidato registrados com sucesso no Google Sheets!"
                                )
                                # Atualiza o estado para forçar o recarregamento do histórico
                                st.session_state["data_updated"] = True
                            else:
                                st.error("Falha ao registrar dados no Google Sheets.")

                            # --- Visualização no Mapa ---
                            st.subheader("Visualização no Mapa")
                            m = folium.Map(
                                location=[coords_candidato[0], coords_candidato[1]],
                                zoom_start=12,
                            )

                            # Marcador do Candidato
                            folium.Marker(
                                [coords_candidato[0], coords_candidato[1]],
                                tooltip=f"Candidato: {nome_candidato_input}\n{endereco_candidato_input}",
                                icon=folium.Icon(
                                    color="blue", icon="user", prefix="fa"
                                ),
                            ).add_to(m)

                            # Marcadores das Lojas
                            for nome_loja, coords_loja in coords_lojas.items():
                                color = (
                                    "green" if nome_loja == loja_mais_proxima else "red"
                                )
                                icon = (
                                    "store"
                                    if nome_loja == loja_mais_proxima
                                    else "map-marker"
                                )
                                folium.Marker(
                                    [coords_loja[0], coords_loja[1]],
                                    tooltip=f"Loja: {nome_loja}\n{enderecos_lojas[nome_loja]}",
                                    icon=folium.Icon(
                                        color=color, icon=icon, prefix="fa"
                                    ),
                                ).add_to(m)

                            # Adicionar rota ao mapa
                            if geometria_rota_mais_curta:
                                # OSRM retorna GeoJSON, que usa [longitude, latitude], folium precisa [latitude, longitude]
                                # Inverte as coordenadas para o folium
                                inverted_coordinates = [
                                    [coord[1], coord[0]]
                                    for coord in geometria_rota_mais_curta[
                                        "coordinates"
                                    ]
                                ]
                                folium.PolyLine(
                                    inverted_coordinates,
                                    color="blue",
                                    weight=5,
                                    opacity=0.7,
                                    tooltip=f"Rota mais curta para {loja_mais_proxima}: {melhor_distancia_km:.2f} km",
                                ).add_to(m)

                            # Ajusta o mapa para mostrar todos os pontos
                            bounds = [coords_candidato] + list(coords_lojas.values())
                            m.fit_bounds(
                                [
                                    [
                                        min(p[0] for p in bounds),
                                        min(p[1] for p in bounds),
                                    ],
                                    [
                                        max(p[0] for p in bounds),
                                        max(p[1] for p in bounds),
                                    ],
                                ]
                            )

                            st_folium(m, width=700, height=500)

                        else:
                            st.error(
                                "Não foi possível determinar a loja mais próxima. Verifique os endereços e tente novamente."
                            )

# --- Histórico de Candidatos ---
st.markdown("---")
st.header("📊 Histórico de Candidatos")

# Botão para recarregar ou para indicar atualização
if st.button("Atualizar Histórico"):
    st.cache_data.clear()
    st.session_state["data_updated"] = True

dados_historico = carregar_dados_candidatos()

if not dados_historico.empty:
    st.dataframe(dados_historico, use_container_width=True)
    if st.button(
        "Limpar Histórico de Candidatos",
        help="Isso apagará TODOS os dados no Google Sheets para esta aplicação.",
    ):
        if limpar_dados_candidatos():
            st.session_state["data_updated"] = (
                True  # Força o recarregamento após limpar
            )
else:
    st.info(
        "Nenhum dado de candidato encontrado no histórico. Faça uma pesquisa acima para começar."
    )

st.markdown("---")
st.markdown("Desenvolvido com ❤️ e Streamlit")
