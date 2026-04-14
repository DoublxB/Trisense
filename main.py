"""
TriSense - Program Pybricks pentru Hub SPIKE Prime.
Ruleaza pe Hub, citeste senzorul HuskyLens via LMS-ESP32.
"""
from pybricks.parameters import Port
from pybricks.tools import wait
from pupremote import PUPRemoteHub

# Portul unde e conectat cablul LEGO (LMS-ESP32)
SENSOR_PORT = Port.A
LOOP_DELAY_MS = 50  # Sincronizat cu ESP32
INIT_RETRY_MS = 2000

def main():
    # Asteapta stabilizare alimentare - portul porneste la conectare
    wait(500)
    pr = PUPRemoteHub(SENSOR_PORT)
    pr.add_channel("obj", to_hub_fmt="b")
    pr.add_command("cmd", to_hub_fmt="b", from_hub_fmt="b")

    # Comanda curenta (1, 2 sau 3 = ID obiect de detectat)
    cmd_val = 1
    pr.call("cmd", cmd_val)  # Trimite comanda la ESP32

    # Loop principal - citeste obj la fiecare 50ms
    while True:
        obj = pr.call("obj")
        if obj and obj > 0:
            print("Obiect detectat ID:", obj)
        wait(LOOP_DELAY_MS)

if __name__ == "__main__":
    main()
