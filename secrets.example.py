# Incarcare pe LMS-ESP32 (din folderul proiectului, cu portul tau):
# python -m mpremote connect COM7 cp secrets.py :secrets.py
#
# Nu comita secrets.py in git (gitignore).

GEMINI_API_KEY = "AIza...pune_cheia_ta_aici..."

# IP-ul PC-ului pe aceeasi WiFi (server TCP voce din run_voice_dialog.py).
PC_VOICE_IP = "192.168.100.134"

# WiFi robot — SSID / parola retelei Orange 2.4G (sau schimba cu reteaua ta).
WIFI_SSID = "inventika"
WIFI_PASS = "!#inventika2025"

# MQTT — acelasi ca .env pe PC (implicit broker public).
MQTT_BROKER = "192.168.80.106"
