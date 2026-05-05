"""
TriSense - Program Pybricks pentru Hub SPIKE Prime.
Ruleaza pe Hub; brate Port B+E, roti diferentiale Port C+D (cate una pe parte).

Canal PupRemote "cmd" (uint8) — trebuie aliniat cu main_robot.py pe ESP:

  0   idle / fara efect
  1   dans brate
  2–6 miscari brate (repose / stanga / dreapta / inspir / expir)
  7   scurt inainte (roti)
  8   scurt inapoi
  9   pivot stanga (~pe loc)
  10  pivot dreapta
  11  oprire roti (frana)
  12  show respiratie: ~10s, 2 cicluri braț + animatie lumină inspir/expir pe matricea Hub.
  13  emotie trist: brate jos lent, puls lumina slab (Act. 6 Guess the Emotion)
  14  emotie uimit:  brate sus rapid, flash lumina (Act. 6 Guess the Emotion)
  15  emotie fericit: dans brate + roti fata/spate (Act. 6 Guess the Emotion)

Montaj fizic diferit → poti folosi invertire pe un Motor sau schimba C/D sus/jos.

PAS 4 Pe PC: ghid vocal Audio TCP (PCM de pe laptop); MQTT doar action breathing_show — fără speak pe ESP/Gemini.
"""

from pybricks.hubs import PrimeHub
from pybricks.pupdevices import Motor
from pybricks.parameters import Port, Direction, Stop
from pybricks.tools import wait
from pupremote_hub import PUPRemoteHub

# Portul unde e conectat cablul LEGO (LMS-ESP32)
SENSOR_PORT = Port.A
LOOP_DELAY_MS = 50

ARM_LEFT_PORT = Port.B
ARM_RIGHT_PORT = Port.E
WHEEL_LEFT_PORT = Port.C
WHEEL_RIGHT_PORT = Port.D

_SPEED = 500
_WHEEL_SPEED_DEG_S = 300
_WHEEL_MS = 650
_ANGLE_DANCE = 60
_ANGLE_SIDE = 45
_ANGLE_OPEN = 55

# Aceleași timing-uri ca BV + PCM inspir/expir în main_robot. `_BSHOW_CYCLES` = `_BV_BREATHING_CYCLES`.
_BSHOW_CYCLES = 2
_BSHOW_INH_MS = 2500
_BSHOW_EXH_MS = 2500


def _matrix_clear(hub):
    try:
        hub.display.off()
    except Exception:
        pass


def _matrix_wave_inspire(hub, total_ms):
    """Rânduri luminoase de jos în sus (~inspiratie). Pybricks: pixel(row,col)."""
    rows = tuple(range(4, -1, -1))
    step = max(total_ms // len(rows), 40)
    for row in rows:
        for col in range(5):
            try:
                hub.display.pixel(row, col, 90)
            except Exception:
                pass
        wait(step)


def _matrix_wave_expire(hub, total_ms):
    """Stinge de sus în jos (~expiratie)."""
    step = max(total_ms // 5, 40)
    for row in range(5):
        for col in range(5):
            try:
                hub.display.pixel(row, col, 0)
            except Exception:
                pass
        wait(step)


def _draw_smiley(hub, brightness=90):
    """Smiley face 5x5 pe matricea Hub."""
    hub.display.off()
    hub.display.pixel(1, 1, brightness)   # ochi stanga
    hub.display.pixel(1, 3, brightness)   # ochi dreapta
    hub.display.pixel(3, 0, brightness)   # zambet colt stanga
    hub.display.pixel(3, 4, brightness)   # zambet colt dreapta
    hub.display.pixel(4, 1, brightness)   # zambet
    hub.display.pixel(4, 2, brightness)   # zambet mijloc
    hub.display.pixel(4, 3, brightness)   # zambet


def _draw_sad_face(hub, brightness=50):
    """Sad face 5x5 pe matricea Hub."""
    hub.display.off()
    hub.display.pixel(1, 1, brightness)   # ochi stanga
    hub.display.pixel(1, 3, brightness)   # ochi dreapta
    hub.display.pixel(3, 1, brightness)   # gura trista
    hub.display.pixel(3, 2, brightness)   # gura trista mijloc
    hub.display.pixel(3, 3, brightness)   # gura trista
    hub.display.pixel(4, 0, brightness)   # colt gura stanga
    hub.display.pixel(4, 4, brightness)   # colt gura dreapta


def _draw_surprised_face(hub, brightness=100):
    """Surprised face 5x5 conform layout utilizator."""
    hub.display.off()
    # Rând 1: X . . . X  (ochi)
    hub.display.pixel(1, 0, brightness)
    hub.display.pixel(1, 4, brightness)
    # Rând 2: . X X X .  (gura sus)
    hub.display.pixel(2, 1, brightness)
    hub.display.pixel(2, 2, brightness)
    hub.display.pixel(2, 3, brightness)
    # Rând 3: . X . X .  (gura lateral)
    hub.display.pixel(3, 1, brightness)
    hub.display.pixel(3, 3, brightness)
    # Rând 4: . X X X .  (gura jos)
    hub.display.pixel(4, 1, brightness)
    hub.display.pixel(4, 2, brightness)
    hub.display.pixel(4, 3, brightness)


def _arms_home(arm_left, arm_right):
    arm_left.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, 0, then=Stop.HOLD, wait=True)


def dance_arms_and_wheels(arm_left, arm_right, w_left, w_right):
    """Miscare dans: brate + roti fata/spate alternativ."""
    for _ in range(3):
        arm_left.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        w_left.run_time(_WHEEL_SPEED_DEG_S, 600, then=Stop.BRAKE, wait=False)
        w_right.run_time(_WHEEL_SPEED_DEG_S, 600, then=Stop.BRAKE, wait=True)
        arm_left.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        w_left.run_time(-_WHEEL_SPEED_DEG_S, 600, then=Stop.BRAKE, wait=False)
        w_right.run_time(-_WHEEL_SPEED_DEG_S, 600, then=Stop.BRAKE, wait=True)
    _arms_home(arm_left, arm_right)


def repose_pose(arm_left, arm_right):
    _arms_home(arm_left, arm_right)


def left_arm_up_pose(arm_left, arm_right):
    arm_left.run_target(_SPEED, _ANGLE_SIDE, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, 0, then=Stop.HOLD, wait=True)


def right_arm_up_pose(arm_left, arm_right):
    arm_left.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, _ANGLE_SIDE, then=Stop.HOLD, wait=True)


def breathe_in_pose(arm_left, arm_right):
    arm_left.run_target(_SPEED, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, _ANGLE_OPEN, then=Stop.HOLD, wait=True)


def breathe_out_pose(arm_left, arm_right):
    _arms_home(arm_left, arm_right)


def emotion_happy_routine(arm_left, arm_right, w_left, w_right, hub):
    """Cmd 15 — bucurie: smiley face + dans brate + roti fata/spate."""
    _draw_smiley(hub)
    # Ciclu 1: brate sus + roti inainte
    arm_left.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=True)
    w_left.run_time(_WHEEL_SPEED_DEG_S, 1200, then=Stop.BRAKE, wait=False)
    w_right.run_time(_WHEEL_SPEED_DEG_S, 1200, then=Stop.BRAKE, wait=True)
    # Ciclu 2: brate jos + roti inapoi
    arm_left.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=True)
    w_left.run_time(-_WHEEL_SPEED_DEG_S, 1200, then=Stop.BRAKE, wait=False)
    w_right.run_time(-_WHEEL_SPEED_DEG_S, 1200, then=Stop.BRAKE, wait=True)
    # Ciclu 3: brate sus din nou + roti inainte
    _draw_smiley(hub)
    arm_left.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=True)
    w_left.run_time(_WHEEL_SPEED_DEG_S, 1200, then=Stop.BRAKE, wait=False)
    w_right.run_time(_WHEEL_SPEED_DEG_S, 1200, then=Stop.BRAKE, wait=True)
    _arms_home(arm_left, arm_right)
    hub.display.off()


def emotion_sad_routine(arm_left, arm_right, hub):
    """Cmd 13 — tristete: sad face + brate jos + animatie lacrimi."""
    _draw_sad_face(hub)
    arm_left.run_target(_SPEED // 3, -(_ANGLE_SIDE // 2), then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED // 3, -(_ANGLE_SIDE // 2), then=Stop.HOLD, wait=True)
    # Animatie lacrimi: 3 runde, picaturi cad pe col 1 si col 3 (sub ochi)
    for _ in range(3):
        _draw_sad_face(hub)
        wait(400)
        for row in range(2, 5):
            hub.display.pixel(row, 1, 90)   # lacrima stanga
            hub.display.pixel(row, 3, 90)   # lacrima dreapta
            wait(320)
            hub.display.pixel(row, 1, 0)
            hub.display.pixel(row, 3, 0)
    _arms_home(arm_left, arm_right)
    hub.display.off()


def emotion_surprised_routine(arm_left, arm_right, hub):
    """Cmd 14 — uimire: surprised face + brate sus rapid + flash alternant."""
    _draw_surprised_face(hub)
    arm_left.run_target(_SPEED * 2, _ANGLE_SIDE, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED * 2, _ANGLE_SIDE, then=Stop.HOLD, wait=True)
    # Flash alternant: fata uimita <-> ecran plin, de 3 ori
    for _ in range(3):
        for row in range(5):
            for col in range(5):
                hub.display.pixel(row, col, 100)
        wait(220)
        _draw_surprised_face(hub)
        wait(220)
    wait(600)
    _arms_home(arm_left, arm_right)
    hub.display.off()


def breathing_show_routine(arm_left, arm_right, hub):
    """PAS 4 — ~10s: brațe + matrix; sunet inspir/expir doar PCM pe ESP dacă uplodat."""
    inh_ms = _BSHOW_INH_MS
    exh_ms = _BSHOW_EXH_MS
    n = _BSHOW_CYCLES
    _matrix_clear(hub)
    for k in range(n):
        print("Breathing show", k + 1, "/", n)
        breathe_in_pose(arm_left, arm_right)
        _matrix_wave_inspire(hub, inh_ms)
        breathe_out_pose(arm_left, arm_right)
        _matrix_wave_expire(hub, exh_ms)
    _matrix_clear(hub)
    print("Breathing show end")


def wheels_forward(w_left, w_right):
    w_left.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=False)
    w_right.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=True)


def wheels_backward(w_left, w_right):
    w_left.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=False)
    w_right.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=True)


def wheels_turn_left(w_left, w_right):
    w_left.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=False)
    w_right.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=True)


def wheels_turn_right(w_left, w_right):
    w_left.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=False)
    w_right.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=True)


def wheels_brake(w_left, w_right):
    w_left.stop()
    w_right.stop()


def run_cmd(arm_left, arm_right, w_left, w_right, hub, code):
    if code == 1:
        print("Dance!")
        dance_arms_and_wheels(arm_left, arm_right, w_left, w_right)
    elif code == 2:
        print("Repose")
        repose_pose(arm_left, arm_right)
    elif code == 3:
        print("Left arm")
        left_arm_up_pose(arm_left, arm_right)
    elif code == 4:
        print("Right arm")
        right_arm_up_pose(arm_left, arm_right)
    elif code == 5:
        print("Breathe in")
        breathe_in_pose(arm_left, arm_right)
    elif code == 6:
        print("Breathe out")
        breathe_out_pose(arm_left, arm_right)
    elif code == 7:
        print("Drive FWD")
        wheels_forward(w_left, w_right)
    elif code == 8:
        print("Drive back")
        wheels_backward(w_left, w_right)
    elif code == 9:
        print("Turn L")
        wheels_turn_left(w_left, w_right)
    elif code == 10:
        print("Turn R")
        wheels_turn_right(w_left, w_right)
    elif code == 11:
        print("Wheels stop")
        wheels_brake(w_left, w_right)
    elif code == 12:
        print("Breathing SHOW")
        breathing_show_routine(arm_left, arm_right, hub)
    elif code == 13:
        print("Emotion SAD")
        emotion_sad_routine(arm_left, arm_right, hub)
    elif code == 14:
        print("Emotion SURPRISED")
        emotion_surprised_routine(arm_left, arm_right, hub)
    elif code == 15:
        print("Emotion HAPPY")
        emotion_happy_routine(arm_left, arm_right, w_left, w_right, hub)
    else:
        pass


def main():
    hub = PrimeHub()

    arm_left = Motor(ARM_LEFT_PORT)
    arm_right = Motor(ARM_RIGHT_PORT, positive_direction=Direction.COUNTERCLOCKWISE)
    wheel_left = Motor(WHEEL_LEFT_PORT)
    wheel_right = Motor(WHEEL_RIGHT_PORT, positive_direction=Direction.COUNTERCLOCKWISE)

    wait(500)

    while True:
        # (Re)initializare PupRemote — daca ESP se deconecteaza, refacem canalele.
        try:
            pr = PUPRemoteHub(SENSOR_PORT)
            pr.add_channel("obj", to_hub_fmt="b")
            pr.add_channel("cmd", to_hub_fmt="b")
            print("LPF2 init OK — astept comenzi")
        except OSError as e:
            print("LPF2 init err:", e, "— retry 2s")
            wait(2000)
            continue

        last_cmd = 0

        try:
            while True:
                obj = pr.call("obj")
                if obj and obj > 0:
                    print("Obiect detectat ID:", obj)

                cmd = pr.call("cmd")
                cmd_val = cmd if isinstance(cmd, int) else 0
                if cmd_val < 0 or cmd_val > 255:
                    cmd_val = 0

                if cmd_val != 0 and cmd_val != last_cmd:
                    run_cmd(arm_left, arm_right, wheel_left, wheel_right, hub, cmd_val)

                last_cmd = cmd_val
                wait(LOOP_DELAY_MS)
        except OSError as e:
            print("LPF2 pierdut:", e, "— reconectez...")
            wait(1000)


main()
