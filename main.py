import streamlit as st
import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import time

# --- Configurações ---
# API pública do OSRM (lembre-se dos limites de uso!)
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/driving/"
# User-Agent para o Nominatim (importante para identificação)
NOMINATIM_USER_AGENT = (
    "minha-aplicacao-lojas-streamlit"  # Altere para um nome único para sua aplicação
)

# --- Seus 7 endereços de lojas ---
# Dica: Use o formato mais completo possível para melhor precisão na geocodificação
# Exemplo: "Rua dos Tamoios, 300, Centro, Belo Horizonte, MG, Brasil"
enderecos_lojas = {
    "Loja Centro": "Rua dos Tamoios, 300, Centro, Belo Horizonte, MG, Brasil",
    "Loja Savassi": "Rua Pernambuco, 1000, Savassi, Belo Horizonte, MG, Brasil",
    "Loja Pampulha": "Avenida Otacílio Negrão de Lima, 6000, Pampulha, Belo Horizonte, MG, Brasil",
    "Loja Contagem": "Avenida João César de Oliveira, 200, Eldorado, Contagem, MG, Brasil",
    "Loja Betim": "Rua do Rosário, 150, Centro, Betim, MG, Brasil",
    "Loja Vespasiano": "Avenida Thales Chagas, 50, Centro, Vespasiano, MG, Brasil",
    "Loja Nova Lima": "Alameda Oscar Niemeyer, 500, Vale do Sereno, Nova Lima, MG, Brasil",
}

# --- Funções Auxiliares (com cache para Streamlit) ---


@st.cache_data(
    ttl=3600
)  # Cacheia o resultado por 1 hora para evitar chamadas repetidas
def geocodificar_endereco(endereco):
    """Converte um endereço textual em coordenadas de latitude e longitude."""
    geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT)
    try:
        location = geolocator.geocode(endereco, timeout=10)
        if location:
            return location.latitude, location.longitude
        st.warning(
            f"Não foi possível geocodificar o endereço: '{endereco}'. Verifique a digitação."
        )
        return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        st.error(
            f"Erro de geocodificação para '{endereco}': {e}. Tente novamente mais tarde."
        )
        return None


@st.cache_data(ttl=3600)  # Cacheia o resultado por 1 hora
def obter_distancia_osrm(coord_origem, coord_destino):
    """Obtém a distância real da rota (em km) e o tempo (em segundos) via OSRM."""
    if not coord_origem or not coord_destino:
        return None, None

    url = f"{OSRM_BASE_URL}{coord_origem[1]},{coord_origem[0]};{coord_destino[1]},{coord_destino[0]}?overview=false"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        if data and "routes" in data and len(data["routes"]) > 0:
            distance_meters = data["routes"][0]["distance"]
            duration_seconds = data["routes"][0]["duration"]
            return distance_meters / 1000, duration_seconds
        else:
            st.warning(
                f"Nenhuma rota encontrada via OSRM entre os pontos. Verifique as coordenadas."
            )
            return None, None
    except requests.exceptions.RequestException as e:
        st.error(
            f"Erro de requisição OSRM: {e}. O serviço pode estar indisponível ou você atingiu o limite de requisições."
        )
        return None, None


# --- Interface Streamlit ---
st.set_page_config(page_title="Localizador de Loja Mais Próxima", page_icon="📍")

st.title("📍 Localizador de Loja Mais Próxima")
st.write(
    "Insira o endereço do candidato para encontrar qual das suas lojas é a mais próxima pela rota."
)

endereco_candidato_input = st.text_input(
    "Endereço do Candidato (Ex: Rua da Paz, 20, Belo Horizonte, MG, Brasil)",
    placeholder="Digite o endereço completo aqui...",
)

if st.button("Encontrar Loja Mais Próxima"):
    if not endereco_candidato_input:
        st.warning("Por favor, digite o endereço do candidato.")
    else:
        with st.spinner(
            "Calculando a loja mais próxima... Isso pode levar alguns segundos."
        ):
            # 1. Geocodificar o endereço do candidato
            coords_candidato = geocodificar_endereco(endereco_candidato_input)

            if not coords_candidato:
                st.error(
                    "Não foi possível processar o endereço do candidato. Tente novamente."
                )
            else:
                # 2. Geocodificar os endereços das lojas (se ainda não estiverem em cache)
                coords_lojas = {}
                for nome_loja, endereco_completo in enderecos_lojas.items():
                    coords = geocodificar_endereco(endereco_completo)
                    if coords:
                        coords_lojas[nome_loja] = coords
                    time.sleep(0.1)  # Pequena pausa para evitar sobrecarga no Nominatim

                if not coords_lojas:
                    st.error(
                        "Nenhuma das lojas pôde ser geocodificada. Verifique os endereços pré-definidos."
                    )
                else:
                    # 3. Calcular distâncias de rota e encontrar a mais próxima
                    melhor_distancia_km = float("inf")
                    melhor_tempo_seg = float("inf")
                    loja_mais_proxima = None

                    for nome_loja, coords_loja in coords_lojas.items():
                        dist_km, tempo_seg = obter_distancia_osrm(
                            coords_candidato, coords_loja
                        )

                        if dist_km is not None and tempo_seg is not None:
                            if dist_km < melhor_distancia_km:
                                melhor_distancia_km = dist_km
                                melhor_tempo_seg = tempo_seg
                                loja_mais_proxima = nome_loja
                        time.sleep(0.1)  # Pequena pausa para evitar sobrecarga no OSRM

                    if loja_mais_proxima:
                        st.success("--- Resultado ---")
                        st.markdown(
                            f"A loja mais próxima do candidato é: **{loja_mais_proxima}**."
                        )
                        st.markdown(
                            f"Distância da rota: **{melhor_distancia_km:.2f} km**."
                        )
                        st.markdown(
                            f"Tempo de viagem estimado: **{melhor_tempo_seg / 60:.1f} minutos**."
                        )
                        st.info(
                            "As distâncias são calculadas pela rota de carro e podem variar com o tráfego."
                        )
                    else:
                        st.error(
                            "Não foi possível determinar a loja mais próxima. Verifique os endereços e tente novamente."
                        )

st.markdown("---")
st.markdown("Desenvolvido com ❤️ e Streamlit")
