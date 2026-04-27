"""
TriSense - Program Pybricks pentru Hub SPIKE Prime.
Ruleaza pe Hub, citeste senzorul HuskyLens via LMS-ESP32.
Raspunde la comanda "dance" (cmd=1 de la ESP32) miscand bratele pe porturile E si B.
"""
from pybricks.hubs import PrimeHub
from pybricks.pupdevices import Motor
from pybricks.parameters import Port, Direction, Stop
from pybricks.tools import wait
from pupremote_hub import PUPRemoteHub

# Portul unde e conectat cablul LEGO (LMS-ESP32)
SENSOR_PORT = Port.A
LOOP_DELAY_MS = 50

# Porturile motoarelor de la brate
MOTOR_LEFT_PORT = Port.B
MOTOR_RIGHT_PORT = Port.E


def dance_arms(arm_left, arm_right):
    """Misca bratele in sus si jos de 4 ori ca dans."""
    speed = 500
    angle = 60
    for _ in range(4):
        arm_left.run_target(speed, angle, then=Stop.HOLD, wait=False)
        arm_right.run_target(speed, angle, then=Stop.HOLD, wait=True)
        arm_left.run_target(speed, -angle, then=Stop.HOLD, wait=False)
        arm_right.run_target(speed, -angle, then=Stop.HOLD, wait=True)
    # Revino la pozitia 0 (neutra)
    arm_left.run_target(speed, 0, then=Stop.HOLD, wait=False)
    arm_right.run_target(speed, 0, then=Stop.HOLD, wait=True)


def main():
    hub = PrimeHub()

    arm_left = Motor(MOTOR_LEFT_PORT)
    arm_right = Motor(MOTOR_RIGHT_PORT, positive_direction=Direction.COUNTERCLOCKWISE)

    # Asteapta stabilizare alimentare
    wait(500)

    pr = PUPRemoteHub(SENSOR_PORT)
    # Trebuie sa corespunda EXACT cu add_channel din main_robot.py de pe ESP32
    pr.add_channel("obj", to_hub_fmt="b")
    pr.add_channel("cmd", to_hub_fmt="b")

    last_cmd = 0

    while True:
        obj = pr.call("obj")
        if obj and obj > 0:
            print("Obiect detectat ID:", obj)

        cmd = pr.call("cmd")
        cmd_val = cmd if isinstance(cmd, int) else 0

        # Detectam tranzitia 0->1 ca sa nu repetam dansul cat timp cmd ramane 1
        if cmd_val == 1 and last_cmd != 1:
            print("Dance! Misc bratele...")
            dance_arms(arm_left, arm_right)

        last_cmd = cmd_val
        wait(LOOP_DELAY_MS)


main()
