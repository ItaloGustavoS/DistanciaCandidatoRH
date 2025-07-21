import datetime
import os
import time
import json
import streamlit as st
import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import pandas as pd  # Ainda necessário para pd.NA, mas não para DataFrames de histórico
import folium
from streamlit_folium import st_folium
import pytz

# --- Configurações ---
# API pública do OSRM
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/driving/"
# User-Agent para o Nominatim
NOMINATIM_USER_AGENT = "minha-aplicacao-lojas-streamlit-v8"  # Alterado para v8

# Fuso horário de Brasília (ainda útil se precisar exibir data/hora da pesquisa atual)
BRAZIL_TIMEZONE = pytz.timezone("America/Sao_Paulo")

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


# --- Funções para Gerar o Mapa (agora para uma única pesquisa) ---
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
    )  # Centro em BH se candidato não for geocodificado
    m = folium.Map(location=map_center, zoom_start=12)

    # Marcador do Candidato
    if coords_candidato:
        folium.Marker(
            [coords_candidato[0], coords_candidato[1]],
            tooltip=f"Candidato: {endereco_candidato}<br>Coordenadas: ({coords_candidato[0]:.4f}, {coords_candidato[1]:.4f})",
            icon=folium.Icon(color="blue", icon="user", prefix="fa"),
        ).add_to(m)

    # Marcador da Loja Mais Próxima
    if coords_loja_mais_proxima:
        folium.Marker(
            [coords_loja_mais_proxima[0], coords_loja_mais_proxima[1]],
            tooltip=f"Loja: {loja_mais_proxima_nome}<br>Endereço: {endereco_loja_mais_proxima}<br>Coordenadas: ({coords_loja_mais_proxima[0]:.4f}, {coords_loja_mais_proxima[1]:.4f})",
            icon=folium.Icon(color="red", icon="store", prefix="fa"),
        ).add_to(m)

    # Desenhar a rota
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

    # Ajustar o zoom para cobrir os pontos
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
        m.zoom_start = 14  # Zoom mais próximo para um único ponto

    st_folium(m, width=700, height=500)


# --- Interface Streamlit ---
st.set_page_config(
    page_title="Localizador de Loja Mais Próxima", page_icon="📍", layout="wide"
)

st.title("📍 Localizador de Loja Mais Próxima")
st.write("Insira o endereço para encontrar a loja mais próxima.")

# --- Entrada de Dados do Candidato ---
with st.container():
    st.header("Endereço para Pesquisa")
    endereco_candidato_input = st.text_input(
        "Endereço (Ex: Avenida Afonso Pena, 1000, Centro, Belo Horizonte, MG, Brasil)",
        placeholder="Digite o endereço completo como o do exemplo aqui...",
    )

    if st.button("Encontrar Loja"):
        if not endereco_candidato_input:
            st.warning("Por favor, preencha o endereço para pesquisa.")
        else:
            with st.spinner(
                "Calculando a loja mais próxima... Isso pode levar alguns segundos."
            ):
                coords_candidato = geocodificar_endereco(endereco_candidato_input)

                if not coords_candidato:
                    st.error(
                        "Não foi possível processar o endereço. A geocodificação falhou. Por favor, revise o endereço e tente novamente."
                    )
                else:
                    st.markdown(f"**Endereço Pesquisado:** {endereco_candidato_input}")
                    st.markdown(
                        f"**Coordenadas:** Latitude: **{coords_candidato[0]:.6f}**, Longitude: **{coords_candidato[1]:.6f}**"
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
                        melhor_distancia_km = float("inf")
                        melhor_tempo_seg = float("inf")
                        loja_mais_proxima_nome = None
                        endereco_loja_selecionada = None
                        coords_loja_selecionada = None
                        geometry_rota_selecionada = None

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
                                    loja_mais_proxima_nome = nome_loja
                                    endereco_loja_selecionada = enderecos_lojas[
                                        nome_loja
                                    ]
                                    coords_loja_selecionada = coords_loja
                                    geometry_rota_selecionada = geometry
                            time.sleep(0.5)
                            progress_bar.progress((i + 1) / len(coords_lojas))

                        if loja_mais_proxima_nome:
                            st.success("--- Resultado da Pesquisa ---")
                            st.markdown(
                                f"A loja mais próxima é: **{loja_mais_proxima_nome}**."
                            )
                            st.markdown(
                                f"Endereço da Loja Mais Próxima: **{endereco_loja_selecionada}**."
                            )
                            st.markdown(
                                f"Distância da rota: **{melhor_distancia_km:.2f} km**."
                            )
                            st.markdown(
                                f"Tempo de viagem estimado: **{melhor_tempo_seg / 60:.1f} minutos**."
                            )

                            st.markdown("---")
                            st.subheader("🌍 Mapa da Rota")
                            gerar_mapa_pesquisa(
                                coords_candidato,
                                endereco_candidato_input,
                                loja_mais_proxima_nome,
                                coords_loja_selecionada,
                                endereco_loja_selecionada,
                                geometry_rota_selecionada,
                            )
                            st.markdown("---")

                        else:
                            st.error(
                                "Não foi possível determinar a loja mais próxima. Verifique o endereço informado, os serviços de geocodificação (Nominatim) e de rota (OSRM) e tente novamente."
                            )

st.markdown("Desenvolvido com ❤️ e Streamlit")
