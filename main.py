import datetime
import os
import time
import json
import traceback
import unicodedata
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
NOMINATIM_USER_AGENT = "minha-aplicacao-lojas-streamlit-vFinal"  # Versão final

# Nome do arquivo JSON com as credenciais do Google Sheets
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"
# Nome da sua planilha do Google Sheets para o LOG
GOOGLE_LOG_SHEET_NAME = (
    "Log Pesquisas Lojas"  # Mantenha este nome consistente com sua planilha
)

# Fuso horário de Brasília
BRAZIL_TIMEZONE = pytz.timezone("America/Sao_Paulo")

# --- Seus 7 endereços de lojas ---
# Mantenha os endereços o mais completos possível.
# Acentuação será removida automaticamente pela função de normalização.
# Se um endereço ainda falhar na geocodificação, verifique-o em um mapa online.
enderecos_lojas = {
    "Loja Lourdes": "Rua Marilia de Dirceu, 161, Lourdes, Belo Horizonte, MG, Brasil",
    "Loja Anchieta": "Avenida dos Bandeirantes, 1733, Anchieta, Belo Horizonte, MG, Brasil",
    "Loja Savassi": "Rua Lavras, 96, Savassi, Belo Horizonte, MG, Brasil",
    "Loja Vila da Serra - Oscar Niemeyer": "Alameda Oscar Niemeyer, 1033, Vila da Serra, Nova Lima, MG, Brasil",
    "Loja Santo Agostinho": "Avenida Olegario Maciel, 1600, Santo Agostinho, Belo Horizonte, MG, Brasil",
    "Loja Vila da Serra - Diciola": "Rua Diciola Horta, 77, Belvedere, Belo Horizonte, MG, Brasil",
    "Loja Belvedere": "BR 356, 3049, Belvedere, Belo Horizonte, MG, Brasil",
}

# --- Funções Auxiliares ---


def normalize_address(address):
    """
    Remove acentos, converte para minúsculas e remove espaços extras.
    Ajuda o Nominatim a interpretar melhor.
    """
    if not isinstance(address, str):
        return address
    address = (
        unicodedata.normalize("NFKD", address).encode("ascii", "ignore").decode("utf-8")
    )
    address = (
        address.replace(".", "").replace(",", "").strip()
    )  # Remove pontuação comum
    address = " ".join(address.split())  # Remove múltiplos espaços
    return address


# --- Funções de Geocodificação e OSRM (com cache) ---


@st.cache_data(ttl=3600)
def geocodificar_endereco(endereco_original):
    endereco_normalizado = normalize_address(endereco_original)
    geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT)
    try:
        location = geolocator.geocode(endereco_normalizado, timeout=10)
        if location:
            return location.latitude, location.longitude

        msg = (
            f"❌ Falha na geocodificação de '{endereco_original}'. "
            f"Tentado como '{endereco_normalizado}'. "
            "Verifique a digitação, complete com cidade, estado e país. "
            "Pode ser que o endereço não exista ou esteja mal formatado para a base de dados do Nominatim."
        )
        st.warning(msg)
        adicionar_log(endereco_original, "ERRO_GEOCODIFICACAO", msg)
        return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        msg = (
            f"🚨 Erro de serviço na geocodificação para '{endereco_original}': {e}. "
            "O servidor de geocodificação pode estar temporariamente indisponível "
            "ou a conexão de rede falhou. Tente novamente mais tarde."
        )
        st.error(msg)
        adicionar_log(
            endereco_original,
            "ERRO_SERVICO_GEOCODIFICACAO",
            msg + f" Traceback: {traceback.format_exc()}",
        )
        return None
    except Exception as e:
        msg = (
            f"⛔ Erro inesperado ao geocodificar '{endereco_original}': {e}. "
            "Isso pode indicar um problema interno. Por favor, contate o suporte."
        )
        st.error(msg)
        adicionar_log(
            endereco_original,
            "ERRO_INESPERADO_GEOCODIFICACAO",
            msg + f" Traceback: {traceback.format_exc()}",
        )
        return None


@st.cache_data(ttl=3600)
def obter_distancia_osrm(coord_origem, coord_destino):
    if not coord_origem or not coord_destino:
        return None, None, None

    url = f"{OSRM_BASE_URL}{coord_origem[1]},{coord_origem[0]};{coord_destino[1]},{coord_destino[0]}?overview=full&steps=true&geometries=geojson"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Lança HTTPError para status de erro (4xx ou 5xx)
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
                msg = (
                    f"⚠️ OSRM: Dados de rota incompletos ou ausentes entre "
                    f"Origem: ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) e "
                    f"Destino: ({coord_destino[0]:.4f}, {coord_destino[1]:.4f}). "
                    "A rota foi encontrada, mas informações essenciais estão faltando."
                )
                st.warning(msg)
                adicionar_log(
                    f"Coords OSRM: {coord_origem} -> {coord_destino}",
                    "AVISO_OSRM_INCOMPLETO",
                    msg,
                )
                return None, None, None
        else:
            msg = (
                f"🚫 OSRM: Nenhuma rota encontrada entre "
                f"Origem: ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) e "
                f"Destino: ({coord_destino[0]:.4f}, {coord_destino[1]:.4f}). "
                "Pode ser que os pontos estejam em locais inacessíveis por estrada ou muito distantes."
            )
            st.warning(msg)
            adicionar_log(
                f"Coords OSRM: {coord_origem} -> {coord_destino}",
                "AVISO_OSRM_SEM_ROTA",
                msg,
            )
            return None, None, None
    except requests.exceptions.HTTPError as e:
        msg = (
            f"❌ Erro HTTP OSRM ({e.response.status_code}) ao tentar rota de "
            f"({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) para ({coord_destino[0]:.4f}, {coord_destino[1]:.4f}): {e.response.text}. "
            "Isso pode indicar um erro no servidor OSRM ou um problema com as coordenadas enviadas."
        )
        st.error(msg)
        adicionar_log(
            f"Coords OSRM: {coord_origem} -> {coord_destino}",
            "ERRO_HTTP_OSRM",
            msg + f" Traceback: {traceback.format_exc()}",
        )
        return None, None, None
    except requests.exceptions.ConnectionError as e:
        msg = (
            f"🚨 Erro de conexão OSRM de ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) para ({coord_destino[0]:.4f}, {coord_destino[1]:.4f}): {e}. "
            "O serviço OSRM pode estar offline ou há um problema de rede."
        )
        st.error(msg)
        adicionar_log(
            f"Coords OSRM: {coord_origem} -> {coord_destino}",
            "ERRO_CONEXAO_OSRM",
            msg + f" Traceback: {traceback.format_exc()}",
        )
        return None, None, None
    except requests.exceptions.Timeout as e:
        msg = (
            f"⏰ Tempo limite excedido para OSRM de ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) para ({coord_destino[0]:.4f}, {coord_destino[1]:.4f}): {e}. "
            "A requisição demorou muito para responder. Tente novamente mais tarde."
        )
        st.error(msg)
        adicionar_log(
            f"Coords OSRM: {coord_origem} -> {coord_destino}",
            "ERRO_TIMEOUT_OSRM",
            msg + f" Traceback: {traceback.format_exc()}",
        )
        return None, None, None
    except Exception as e:
        msg = (
            f"⛔ Erro inesperado OSRM de ({coord_origem[0]:.4f}, {coord_origem[1]:.4f}) para ({coord_destino[0]:.4f}, {coord_destino[1]:.4f}): {e}. "
            "Contate o suporte."
        )
        st.error(msg)
        adicionar_log(
            f"Coords OSRM: {coord_origem} -> {coord_destino}",
            "ERRO_INESPERADO_OSRM",
            msg + f" Traceback: {traceback.format_exc()}",
        )
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
                f"🚫 Erro: Arquivo de credenciais '{GOOGLE_CREDENTIALS_FILE}' não encontrado "
                "e secret 'GSPREAD_SERVICE_ACCOUNT_JSON' não configurado. Por favor, siga as instruções de configuração."
            )
            return None
        return gc
    except gspread.exceptions.APIError as e:
        st.error(
            f"🚫 Erro de API ao autenticar no Google Sheets: {e}. Verifique suas credenciais "
            "e se as APIs necessárias (Google Sheets API e Google Drive API) estão habilitadas no Google Cloud Console."
        )
        adicionar_log(
            "N/A",
            "ERRO_AUTH_GSHEETS_API",
            f"Erro de autenticação Google Sheets: {e}. Traceback: {traceback.format_exc()}",
        )
        return None
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(
            f"🚫 Planilha '{GOOGLE_LOG_SHEET_NAME}' não encontrada. Verifique se o nome está correto "
            "e se ela está compartilhada com o e-mail da sua conta de serviço do Google."
        )
        adicionar_log(
            "N/A",
            "ERRO_PLANILHA_NAO_ENCONTRADA",
            f"Planilha '{GOOGLE_LOG_SHEET_NAME}' não encontrada. Traceback: {traceback.format_exc()}",
        )
        return None
    except json.JSONDecodeError as e:
        st.error(
            f"🚫 Erro ao ler credenciais JSON: {e}. Verifique o formato do arquivo '{GOOGLE_CREDENTIALS_FILE}' "
            "ou o conteúdo do secret 'GSPREAD_SERVICE_ACCOUNT_JSON'."
        )
        adicionar_log(
            "N/A",
            "ERRO_JSON_CREDENCIAL",
            f"Erro de JSON nas credenciais: {e}. Traceback: {traceback.format_exc()}",
        )
        return None
    except Exception as e:
        st.error(
            f"⛔ Erro inesperado ao autenticar no Google Sheets: {e}. "
            "Por favor, revise as configurações de credenciais."
        )
        adicionar_log(
            "N/A",
            "ERRO_INESPERADO_AUTH_GSHEETS",
            f"Erro inesperado autenticação Google Sheets: {e}. Traceback: {traceback.format_exc()}",
        )
        return None


def adicionar_log(endereco_pesquisado, status, mensagem_log=""):
    gc = get_google_sheet_client()
    if gc is None:
        # A mensagem já foi exibida por get_google_sheet_client()
        # st.warning("Não foi possível adicionar o log: Cliente do Google Sheets não disponível.")
        return False
    try:
        sh = gc.open(GOOGLE_LOG_SHEET_NAME)
        worksheet = sh.sheet1  # Assume que o log vai para a primeira aba

        # Obtém a hora atual no fuso horário de Brasília
        now_utc = datetime.datetime.now(pytz.utc)
        now_br = now_utc.astimezone(BRAZIL_TIMEZONE)
        data_hora_br = now_br.strftime(
            "%d/%m/%Y %H:%M:%S"
        )  # Adicionado segundos para mais granularidade no log

        nova_linha = [data_hora_br, endereco_pesquisado, status, mensagem_log]
        worksheet.append_row(nova_linha)
        return True
    except gspread.exceptions.APIError as e:
        st.error(
            f"🚫 Erro de API ao adicionar log no Google Sheets: {e}. "
            "Verifique as permissões da conta de serviço na planilha. Detalhes no console."
        )
        print(f"ERRO DE LOG GSPREAD API: {e}\n{traceback.format_exc()}")
        return False
    except gspread.exceptions.WorksheetNotFound:
        st.error(
            f"🚫 Aba (worksheet) não encontrada na planilha '{GOOGLE_LOG_SHEET_NAME}'. "
            "Verifique se a primeira aba existe ou se foi renomeada."
        )
        print(f"ERRO DE LOG WORKSHEET NOT FOUND: {traceback.format_exc()}")
        return False
    except Exception as e:
        full_traceback = traceback.format_exc()  # Captura o traceback completo
        st.error(
            f"⛔ Erro inesperado ao adicionar log no Google Sheets: {e}. Detalhes no console."
        )
        print(f"ERRO INESPERADO DE LOG NO GOOGLE SHEETS: {e}\n{full_traceback}")
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
    map_center = (
        coords_candidato if coords_candidato else [-19.919, -43.938]
    )  # Centro BH
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
        # A API OSRM retorna GeoJSON com [longitude, latitude], folium espera [latitude, longitude]
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

    # Ajusta o zoom do mapa para incluir ambos os pontos, se existirem
    if len(all_coords_on_map) == 2:
        min_lat = min(p[0] for p in all_coords_on_map)
        max_lat = max(p[0] for p in all_coords_on_map)
        min_lon = min(p[1] for p in all_coords_on_map)
        max_lon = max(p[1] for p in all_coords_on_map)
        m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])
    elif len(all_coords_on_map) == 1:
        m.location = all_coords_on_map[0]
        m.zoom_start = 14  # Zoom um pouco mais próximo para um único ponto

    st_folium(m, width=700, height=500)


# --- Interface Streamlit ---
st.set_page_config(
    page_title="Localizador de Loja Mais Próxima", page_icon="📍", layout="wide"
)

st.title("📍 Localizador de Loja Mais Próxima")
st.write("Insira o endereço para encontrar a loja mais próxima do Candidato.")

# Inicialização do session_state (se ainda não existirem)
# Este bloco garante que os valores padrão são definidos apenas uma vez
if "results_displayed" not in st.session_state:
    st.session_state["results_displayed"] = False
if "loja_mais_proxima_data" not in st.session_state:
    st.session_state["loja_mais_proxima_data"] = None
if "current_address_input" not in st.session_state:
    st.session_state["current_address_input"] = (
        ""  # Para controlar o input programaticamente
    )

# --- Entrada de Dados ---
with st.container():
    st.header("Endereço para Pesquisa")
    endereco_candidato_input = st.text_input(
        "Endereço (Ex: Avenida Afonso Pena, 1000, Centro, Belo Horizonte, MG, Brasil)",
        placeholder="Digite o endereço completo (rua, número, bairro, cidade, estado, país).",
        help="Removeremos acentos e abreviações para melhor detecção. Ex: 'Rua' ao invés de 'R.'.",
        key="address_input",  # Mantém a chave para Streamlit
        value=st.session_state["current_address_input"],  # Conecta com o session_state
    )

    if st.button("Encontrar Loja"):
        # Limpa resultados anteriores ao iniciar uma nova busca
        st.session_state["results_displayed"] = False
        st.session_state["loja_mais_proxima_data"] = None

        if (
            not endereco_candidato_input or len(endereco_candidato_input.strip()) < 10
        ):  # Aumentei o mínimo para 10
            st.warning(
                "Por favor, preencha um endereço válido e mais completo (mínimo 10 caracteres)."
            )
            adicionar_log(
                endereco_candidato_input,
                "ERRO_VALIDACAO",
                "Endereço inválido/muito curto.",
            )
        else:
            # Normaliza o endereço do candidato ANTES de tentar geocodificar
            endereco_candidato_normalizado = normalize_address(endereco_candidato_input)
            st.info(
                f"Tentando geocodificar o endereço: '{endereco_candidato_normalizado}'"
            )

            with st.spinner(
                "Geocodificando seu endereço e das lojas. Isso pode levar alguns segundos..."
            ):
                coords_candidato = geocodificar_endereco(
                    endereco_candidato_input
                )  # Passa o original para log e msg de erro

                if not coords_candidato:
                    # Mensagem de erro já tratada dentro de geocodificar_endereco
                    pass  # Não faz nada aqui, pois a função já exibiu o erro e logou
                else:
                    coords_lojas = {}
                    lojas_nao_geocodificadas = []

                    # Geocodificação das lojas
                    for nome_loja, endereco_completo_loja in enderecos_lojas.items():
                        coords = geocodificar_endereco(
                            endereco_completo_loja
                        )  # Passa o original da loja
                        if coords:
                            coords_lojas[nome_loja] = coords
                        else:
                            lojas_nao_geocodificadas.append(nome_loja)
                        time.sleep(
                            1
                        )  # Atraso para respeitar a política de uso da API do Nominatim

                    if lojas_nao_geocodificadas:
                        msg_lojas = (
                            f"⚠️ Aviso: As seguintes lojas não puderam ser geocodificadas e foram ignoradas: "
                            f"{', '.join(lojas_nao_geocodificadas)}. "
                            "Verifique os endereços pré-definidos dessas lojas."
                        )
                        st.warning(msg_lojas)
                        adicionar_log(
                            endereco_candidato_input,
                            "AVISO_LOJAS_NAO_GEOCODIFICADAS",
                            msg_lojas,
                        )

                    if not coords_lojas:
                        error_msg = "❌ Nenhuma das lojas pôde ser geocodificada. Não é possível calcular rotas. Verifique os endereços das lojas."
                        st.error(error_msg)
                        adicionar_log(endereco_candidato_input, "ERRO", error_msg)
                    else:
                        melhor_distancia_km = float("inf")
                        melhor_tempo_seg = float("inf")
                        loja_mais_proxima_nome = None
                        endereco_loja_selecionada = None
                        coords_loja_selecionada = None
                        geometry_rota_selecionada = None

                        rotas_com_problema = []

                        # Cálculo das rotas para encontrar a mais próxima
                        for nome_loja, coords_loja in coords_lojas.items():
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
                            else:
                                rotas_com_problema.append(nome_loja)
                            time.sleep(
                                1
                            )  # Atraso para respeitar a política de uso da API do OSRM

                        if rotas_com_problema:
                            msg_rotas = (
                                f"⚠️ Aviso: Não foi possível obter rota para as lojas: "
                                f"{', '.join(rotas_com_problema)}. "
                                "A loja mais próxima foi calculada apenas com as rotas bem-sucedidas."
                            )
                            st.warning(msg_rotas)
                            adicionar_log(
                                endereco_candidato_input, "AVISO_ROTAS_FALHA", msg_rotas
                            )

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
                                f"Sucesso: Loja encontrada: {loja_mais_proxima_nome}. Dist: {melhor_distancia_km:.2f} km.",
                            )
                            st.session_state["current_address_input"] = (
                                ""  # Limpa o campo após sucesso
                            )

                        else:
                            error_msg = "❌ Não foi possível determinar a loja mais próxima. Todos os cálculos de rota falharam ou nenhuma loja pôde ser geocodificada. Por favor, revise o endereço pesquisado e os endereços das lojas."
                            st.error(error_msg)
                            adicionar_log(
                                endereco_candidato_input,
                                "ERRO_NAO_ENCONTRADO",
                                error_msg,
                            )
                            st.session_state["results_displayed"] = False

# Exibir os resultados e o mapa se houver dados na session_state
# Esta parte do código será executada sempre que a página for recarregada ou um botão for clicado
if st.session_state["results_displayed"] and st.session_state["loja_mais_proxima_data"]:
    data = st.session_state["loja_mais_proxima_data"]
    st.success("--- Resultado da Pesquisa ---")
    st.markdown(f"**Endereço Pesquisado:** `{data['endereco_pesquisado']}`")
    st.markdown(
        f"**Coordenadas da Origem:** Latitude: **{data['coords_candidato'][0]:.6f}**, Longitude: **{data['coords_candidato'][1]:.6f}**"
    )
    st.markdown(f"A loja mais próxima é: **{data['loja_mais_proxima_nome']}**.")
    st.markdown(
        f"Endereço da Loja Mais Próxima: **`{data['endereco_loja_selecionada']}`**."
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

st.markdown(
    "Desenvolvido com ❤️ e Streamlit por [Ítalo Gustavo](https://www.linkedin.com/in/italogustavoggsenna/)"
)
