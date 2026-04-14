# Porneste main_robot.py pe LMS-ESP32
# Citeste RECOVERY.md daca primesti "could not enter raw repl"

$COM = "COM6"  # schimba daca e alt port

# Varianta 1: doar run (daca fisierele sunt deja pe device)
Write-Host "Pornire main_robot.py..."
py -m mpremote connect $COM run main_robot.py
