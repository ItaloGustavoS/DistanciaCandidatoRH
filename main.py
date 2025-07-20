from geopy.geocoders import Nominatim
from geopy.distance import geodesic # Para distância em linha reta, pode usar great_circle ou haversine também

# 1. Endereços das lojas (você teria os 7 aqui)
enderecos_lojas = {
    "Loja A": "Rua das Flores, 100, São Paulo, SP",
    "Loja B": "Avenida Brasil, 500, Rio de Janeiro, RJ",
    # ... seus outros 5 endereços
}

# 2. Endereço do candidato
endereco_candidato = "Rua da Paz, 20, Belo Horizonte, MG"

geolocator = Nominatim(user_agent="my-geocoder-app") # Substitua 'my-geocoder-app' por um nome único

coordenadas_lojas = {}
for nome, endereco in enderecos_lojas.items():
    try:
        location = geolocator.geocode(endereco)
        if location:
            coordenadas_lojas[nome] = (location.latitude, location.longitude)
            print(f"Coordenadas de {nome}: {location.latitude}, {location.longitude}")
        else:
            print(f"Não foi possível geocodificar o endereço da {nome}.")
    except Exception as e:
        print(f"Erro ao geocodificar {nome}: {e}")


coordenadas_candidato = None
try:
    location_candidato = geolocator.geocode(endereco_candidato)
    if location_candidato:
        coordenadas_candidato = (location_candidato.latitude, location_candidato.longitude)
        print(f"Coordenadas do candidato: {location_candidato.latitude}, {location_candidato.longitude}")
    else:
        print("Não foi possível geocodificar o endereço do candidato.")
except Exception as e:
    print(f"Erro ao geocodificar o endereço do candidato: {e}")

if coordenadas_candidato and coordenadas_lojas:
    distancias = {}
    for nome_loja, coords_loja in coordenadas_lojas.items():
        # Calcula a distância em linha reta (geodesic é mais preciso que haversine para grandes distâncias)
        dist = geodesic(coordenadas_candidato, coords_loja).km
        distancias[nome_loja] = dist
        print(f"Distância do candidato para {nome_loja}: {dist:.2f} km")

    # Encontra a loja mais próxima
    loja_mais_proxima = min(distancias, key=distancias.get)
    menor_distancia = distancias[loja_mais_proxima]

    print(f"\n---")
    print(f"A loja mais próxima do candidato é: {loja_mais_proxima} com uma distância de {menor_distancia:.2f} km.")
else:
    print("\nNão foi possível calcular a loja mais próxima devido a erros na geocodificação.")