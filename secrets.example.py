# Incarcare pe LMS-ESP32 (din folderul proiectului, cu portul tau):
# python -m mpremote connect COM7 cp secrets.py :secrets.py
#
# Nu comita secrets.py in git (gitignore).

GEMINI_API_KEY = "AIza...pune_cheia_ta_aici..."

# IP-ul PC-ului pe aceeasi WiFi (server TCP voce) = IPv4 laptop din ipconfig.
PC_VOICE_IP = "192.168.80.106"

# WiFi robot — Inventika (2.4 GHz; ESP si laptop pe aceeasi retea).
WIFI_SSID = "inventika"
WIFI_PASS = "!#inventika2025"

# MQTT — acelasi IP ca MQTT_BROKER din .env pe PC (Mosquitto pe laptop).
MQTT_BROKER = "192.168.80.106"
