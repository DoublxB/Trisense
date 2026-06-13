# Incarcare pe LMS-ESP32 (din folderul proiectului, cu portul tau):
# python -m mpremote connect COM7 cp secrets.py :secrets.py
#
# Nu comita secrets.py in git (gitignore).

# Gol: pe PC folosesti GEMINI_USE_VERTEX=1 + cheie_google.json (nu API key pe ESP).
GEMINI_API_KEY = ""

# IP-ul PC-ului pe aceeasi WiFi (server TCP voce) = IPv4 laptop din ipconfig.
PC_VOICE_IP = "192.168.100.134"

# WiFi robot — Orange 2.4 GHz (ESP si laptop pe aceeasi retea).
WIFI_SSID = "Orange-292q-2.4G"
WIFI_PASS = "Y8kCA4vx"

# MQTT — acelasi IP ca MQTT_BROKER din .env pe PC (Mosquitto pe laptop).
MQTT_BROKER = "192.168.100.134"
