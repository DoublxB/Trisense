# Incarcare pe LMS-ESP32 (din folderul proiectului, cu portul tau):
# python -m mpremote connect COM7 cp secrets.py :secrets.py
#
# Nu comita secrets.py in git (gitignore).

# Gol: pe PC folosesti GEMINI_USE_VERTEX=1 + cheie_google.json (nu API key pe ESP).
GEMINI_API_KEY = ""

# IP-ul PC-ului pe aceeasi WiFi (server TCP voce) = IPv4 laptop din ipconfig.
PC_VOICE_IP = "192.168.x.x"

# WiFi robot — ESP si laptop pe aceeasi retea.
WIFI_SSID = "Numele_Retelei_Tale"
WIFI_PASS = "Parola_Retelei_Tale"

# MQTT — acelasi IP ca MQTT_BROKER din .env pe PC (Mosquitto pe laptop).
MQTT_BROKER = "192.168.x.x"
