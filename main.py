import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import time

# --- Configurações ---
# API pública do OSRM (lembre-se dos limites de uso!)
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/driving/"
# User-Agent para o Nominatim (importante para identificação)
NOMINATIM_USER_AGENT = "minha-aplicacao-lojas"

# --- Seus 7 endereços de lojas ---
# Dica: Use o formato mais completo possível para melhor precisão na geocodificação
enderecos_lojas = {
    "Loja Centro": "Rua dos Tamoios, 300, Centro, Belo Horizonte, MG, Brasil",
    "Loja Savassi": "Rua Pernambuco, 1000, Savassi, Belo Horizonte, MG, Brasil",
    "Loja Pampulha": "Avenida Otacílio Negrão de Lima, 6000, Pampulha, Belo Horizonte, MG, Brasil",
    "Loja Contagem": "Avenida João César de Oliveira, 200, Eldorado, Contagem, MG, Brasil",
    "Loja Betim": "Rua do Rosário, 150, Centro, Betim, MG, Brasil",
    "Loja Vespasiano": "Avenida Thales Chagas, 50, Centro, Vespasiano, MG, Brasil",
    "Loja Nova Lima": "Alameda Oscar Niemeyer, 500, Vale do Sereno, Nova Lima, MG, Brasil",
}

# --- Endereço do candidato ---
endereco_candidato = "Rua Gonçalves Dias, 1200, Lourdes, Belo Horizonte, MG, Brasil"  # Exemplo, você vai inserir este na aplicação


# --- Funções Auxiliares ---
def geocodificar_endereco(endereco):
    """Converte um endereço textual em coordenadas de latitude e longitude."""
    geolocator = Nominatim(user_agent=NOMINATIN_USER_AGENT)
    try:
        location = geolocator.geocode(
            endereco, timeout=10
        )  # Aumentar timeout pode ajudar
        if location:
            return location.latitude, location.longitude
        print(f"ATENÇÃO: Não foi possível geocodificar: {endereco}")
        return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"ERRO de geocodificação para '{endereco}': {e}")
        print("Aguardando 1 segundo antes de tentar novamente...")
        time.sleep(1)  # Aguarda para evitar bloqueio por muitas requisições
        return None  # Retorna None e a função principal irá tratar


def obter_distancia_osrm(coord_origem, coord_destino):
    """Obtém a distância real da rota (em km) e o tempo (em segundos) via OSRM."""
    if not coord_origem or not coord_destino:
        return None, None

    url = f"{OSRM_BASE_URL}{coord_origem[1]},{coord_origem[0]};{coord_destino[1]},{coord_destino[0]}?overview=false"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Levanta um erro para status HTTP ruins (4xx ou 5xx)
        data = response.json()

        if data and "routes" in data and len(data["routes"]) > 0:
            distance_meters = data["routes"][0]["distance"]
            duration_seconds = data["routes"][0]["duration"]
            return distance_meters / 1000, duration_seconds  # Retorna em KM e segundos
        else:
            print(
                f"AVISO OSRM: Nenhuma rota encontrada entre {coord_origem} e {coord_destino}."
            )
            return None, None
    except requests.exceptions.RequestException as e:
        print(f"ERRO de requisição OSRM entre {coord_origem} e {coord_destino}: {e}")
        return None, None


# --- Processo Principal ---
def encontrar_loja_mais_proxima(end_candidato, lista_lojas):
    print("--- Iniciando busca pela loja mais próxima ---")

    # 1. Geocodificar o endereço do candidato
    print(f"\nGeocodificando endereço do candidato: '{end_candidato}'...")
    coords_candidato = geocodificar_endereco(end_candidato)
    if not coords_candidato:
        return "Não foi possível geocodificar o endereço do candidato."
    print(
        f"Coordenadas do candidato: Lat {coords_candidato[0]:.4f}, Long {coords_candidato[1]:.4f}"
    )

    # 2. Geocodificar os endereços das lojas
    coords_lojas = {}
    print("\nGeocodificando endereços das lojas...")
    for nome_loja, endereco_completo in lista_lojas.items():
        print(f"  - {nome_loja}: '{endereco_completo}'")
        coords = geocodificar_endereco(endereco_completo)
        if coords:
            coords_lojas[nome_loja] = coords
            print(f"    -> Coordenadas: Lat {coords[0]:.4f}, Long {coords[1]:.4f}")
        time.sleep(0.5)  # Pequena pausa para não sobrecarregar o Nominatim

    if not coords_lojas:
        return "Nenhuma loja pôde ser geocodificada."

    # 3. Calcular distâncias de rota e encontrar a mais próxima
    melhor_distancia_km = float("inf")
    melhor_tempo_seg = float("inf")
    loja_mais_proxima = None
    distancias_detalhadas = {}

    print("\nCalculando distâncias de rota com OSRM...")
    for nome_loja, coords_loja in coords_lojas.items():
        print(f"  - Calculando rota para: {nome_loja}...")
        dist_km, tempo_seg = obter_distancia_osrm(coords_candidato, coords_loja)

        if dist_km is not None and tempo_seg is not None:
            distancias_detalhadas[nome_loja] = {
                "distancia_km": dist_km,
                "tempo_seg": tempo_seg,
            }
            print(
                f"    -> Distância: {dist_km:.2f} km | Tempo: {tempo_seg / 60:.1f} min"
            )

            if dist_km < melhor_distancia_km:
                melhor_distancia_km = dist_km
                melhor_tempo_seg = tempo_seg
                loja_mais_proxima = nome_loja
        time.sleep(0.5)  # Pequena pausa para não sobrecarregar o OSRM

    if loja_mais_proxima:
        print("\n--- Resultado ---")
        return (
            f"A loja mais próxima do candidato é: **{loja_mais_proxima}**.\n"
            f"Distância da rota: **{melhor_distancia_km:.2f} km**.\n"
            f"Tempo de viagem estimado: **{melhor_tempo_seg / 60:.1f} minutos**."
        )
    else:
        return "Não foi possível determinar a loja mais próxima."


# --- Executar a função ---
resultado = encontrar_loja_mais_proxima(endereco_candidato, enderecos_lojas)
print(resultado)
