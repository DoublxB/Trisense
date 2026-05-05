# Porneste main_robot.py pe LMS-ESP32
# Citeste RECOVERY.md daca primesti "could not enter raw repl"

$COM = "COM7"  # alt port din Manager dispozitive (COM6 / COM8...)

Write-Host "Pornire main_robot.py..."
python -m mpremote connect $COM run main_robot.py
