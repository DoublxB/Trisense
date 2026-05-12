# Incarcare pe LMS-ESP32 (din folderul proiectului, cu portul tau):
# python -m mpremote connect COM7 cp secrets.py :secrets.py
#
# Nu comita secrets.py in git (gitignore).

GEMINI_API_KEY = "AIza...pune_cheia_ta_aici..."

# IP-ul PC-ului pe aceeasi WiFi (server TCP voce). La hotspot (ex. Boca) = IPv4 laptop din ipconfig.
PC_VOICE_IP = "172.20.10.3"

# WiFi robot — exemplu hotspot Boca (2.4 GHz pe telefon; ESP si laptop pe acelasi hotspot).
WIFI_SSID = "Boca"
WIFI_PASS = "parola_hotspot"

# MQTT — acelasi IP ca MQTT_BROKER / PC_VOICE_IP din .env pe PC (Mosquitto pe laptop).
MQTT_BROKER = "172.20.10.3"
