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
NOMINATIM_USER_AGENT = "minha-aplicacao-lojas-streamlit-v3"  # Alterado para v3 para indicar a versão com as últimas correções

# Nome do arquivo JSON com as credenciais do Google Sheets
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"
# Nome da sua planilha do Google Sheets
GOOGLE_SHEET_NAME = "Dados Candidatos Lojas"

# --- Seus 7 endereços de lojas ---
# Mantenha os endereços o mais completo possível para melhor geocodificação
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
            # Inclui a coordenada na mensagem de aviso para depuração
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

    # OSRM espera longitude,latitude. geopy retorna latitude,longitude
    # overview=full para garantir que a geometria esteja sempre presente se a rota for encontrada.
    url = f"{OSRM_BASE_URL}{coord_origem[1]},{coord_origem[0]};{coord_destino[1]},{coord_destino[0]}?overview=full&steps=true&geometries=geojson"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Levanta um erro para status HTTP 4xx/5xx
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
        # Tenta carregar as credenciais de st.secrets (para hospedagem)
        # ou do arquivo local (para desenvolvimento local)
        if (
            "GSPREAD_SERVICE_ACCOUNT_JSON" in st.secrets
        ):  # Usando st.secrets para compatibilidade com secrets.toml
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
    except gspread.exceptions.SpreadsheetNotFound as e:
        st.error(
            f"Planilha '{GOOGLE_SHEET_NAME}' não encontrada ao autenticar. Verifique o nome da planilha e se ela está compartilhada com o e-mail da conta de serviço."
        )
        return None
    except Exception as e:
        st.error(
            f"Erro inesperado ao autenticar no Google Sheets: {e}. Verifique suas credenciais e o formato do secret TOML."
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
                        time.sleep(0.5)  # Pequena pausa para Nominatim

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
                        geometria_rota_mais_curta = None

                        progress_bar = st.progress(0)
                        lojas_com_rotas_validas = {}  # Para usar no mapa

                        for i, (nome_loja, coords_loja) in enumerate(
                            coords_lojas.items()
                        ):
                            # Passa coords_loja para a mensagem de erro do OSRM, se necessário
                            dist_km, tempo_seg, geometry = obter_distancia_osrm(
                                coords_candidato, coords_loja
                            )

                            if (
                                dist_km is not None
                                and tempo_seg is not None
                                and geometry is not None
                            ):
                                lojas_com_rotas_validas[nome_loja] = {
                                    "coords": coords_loja,
                                    "dist_km": dist_km,
                                    "tempo_seg": tempo_seg,
                                    "geometry": geometry,
                                }
                                if dist_km < melhor_distancia_km:
                                    melhor_distancia_km = dist_km
                                    melhor_tempo_seg = tempo_seg
                                    loja_mais_proxima = nome_loja
                                    geometria_rota_mais_curta = geometry
                            time.sleep(0.5)  # Pequena pausa para OSRM
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
                            # Centraliza o mapa no candidato ou em BH se não houver candidato
                            map_center = [coords_candidato[0], coords_candidato[1]]
                            m = folium.Map(location=map_center, zoom_start=12)

                            # Marcador do Candidato
                            folium.Marker(
                                [coords_candidato[0], coords_candidato[1]],
                                tooltip=f"Candidato: {nome_candidato_input}<br>Endereço: {endereco_candidato_input}<br>Coordenadas: ({coords_candidato[0]:.4f}, {coords_candidato[1]:.4f})",
                                icon=folium.Icon(
                                    color="blue", icon="user", prefix="fa"
                                ),
                            ).add_to(m)

                            # Marcadores das Lojas (apenas as que tiveram rota válida ou geocodificação)
                            for (
                                nome_loja,
                                coords_loja,
                            ) in (
                                coords_lojas.items()
                            ):  # Itera sobre todas as lojas que foram geocodificadas
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
                                    tooltip=f"Loja: {nome_loja}<br>Endereço: {enderecos_lojas[nome_loja]}<br>Coordenadas: ({coords_loja[0]:.4f}, {coords_loja[1]:.4f})",
                                    icon=folium.Icon(
                                        color=color, icon=icon, prefix="fa"
                                    ),
                                ).add_to(m)

                            # Adicionar rota mais curta ao mapa
                            if geometria_rota_mais_curta:
                                # OSRM retorna GeoJSON, que usa [longitude, latitude], folium precisa [latitude, longitude]
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
                                    tooltip=f"Rota para {loja_mais_proxima}: {melhor_distancia_km:.2f} km",
                                ).add_to(m)

                            # Ajusta o mapa para mostrar todos os pontos
                            # Inclui o candidato e todas as lojas que foram geocodificadas com sucesso
                            # `bounds` deve conter todas as coordenadas que você quer que o mapa exiba
                            bounds = [coords_candidato] + list(coords_lojas.values())
                            if bounds:  # Garante que há pontos para ajustar o mapa
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
                                "Não foi possível determinar a loja mais próxima. Verifique os endereços informados, os serviços de geocodificação (Nominatim) e de rota (OSRM) e tente novamente."
                            )

# --- Histórico de Candidatos ---
st.markdown("---")
st.header("📊 Histórico de Candidatos")

# Botão para recarregar ou para indicar atualização
if st.button("Atualizar Histórico"):
    st.cache_data.clear()
    st.session_state["data_updated"] = True  # Força o recarregamento

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
