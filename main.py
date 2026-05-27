"""
TriSense - Program Pybricks pentru Hub SPIKE Prime.
Ruleaza pe Hub; brate Port B+E, roti Port C+D, cap/gat Port F (sus-jos).

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
  16  emotie furie: brate rigide + „sprancene” pe ecran + flash rapid (Act. 6 Guess the Emotion)
  17  emotie meltdown: agitatie intensa, brate ample, pivot + fata/spate (Act. 6 Guess the Emotion)

Montaj fizic diferit → poti folosi invertire pe un Motor sau schimba C/D sus/jos.

La handshake cu ESP (LPF2 OK), Hub afiseaza litera „T” mare pe matrice (TriSense).

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
HEAD_PORT = Port.F

_SPEED = 620
_WHEEL_SPEED_DEG_S = 380
_WHEEL_MS = 1050
_ANGLE_DANCE = 92
_ANGLE_SIDE = 72
_ANGLE_OPEN = 88
# Cmd 3–4 (brat sus stanga/dreapta): unghi mare ca miscarea sa fie clara pe scena.
_ANGLE_ARM_PATTERN = 88
# Pivot pe loc (cmd 9–10): mai multa rotatie decat mersul scurt (7–8).
_WHEEL_PIVOT_SPEED = 340
_WHEEL_PIVOT_MS = 900
_WHEEL_DANCE_MS = 950
_WHEEL_EMOTION_MS = 1550
_DANCE_CYCLES = 4
_EMOTION_ARM_EXTRA = 38
# Angry: pivot mai lung + 4 pasi ≈ mini-cerc complet (~360°).
_ANGRY_PIVOT_MS = 1150
_ANGRY_CIRCLE_STEPS = 4

# Aceleași timing-uri ca BV + PCM inspir/expir în main_robot. `_BSHOW_CYCLES` = `_BV_BREATHING_CYCLES`.
_BSHOW_CYCLES = 2
_BSHOW_INH_MS = 2500
_BSHOW_EXH_MS = 2500

# Cap / gat (Port F) — calibrare: daca e invers fizic, schimba semnul sau Direction pe motor.
_HEAD_SPEED = 420
_HEAD_NEUTRAL = 0
_HEAD_UP = 32
_HEAD_DOWN = -24
_HEAD_TILT = 16


def _head_to(head, angle, *, speed=_HEAD_SPEED, wait=True):
    head.run_target(speed, angle, then=Stop.HOLD, wait=wait)


def _head_home(head, *, wait=False):
    _head_to(head, _HEAD_NEUTRAL, wait=wait)


def _head_up(head, *, wait=False):
    _head_to(head, _HEAD_UP, wait=wait)


def _head_down(head, *, wait=False):
    _head_to(head, _HEAD_DOWN, wait=wait)


def _head_nod(head, times=2):
    for _ in range(times):
        _head_up(head, wait=True)
        _head_down(head, wait=True)
    _head_home(head, wait=True)


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


def _draw_T(hub, brightness=100):
    """Literă T mare pe matricea 5×5 — conectat LPF2 / idle TriSense."""
    hub.display.off()
    # Bară sus (tot rândul 0)
    for col in range(5):
        hub.display.pixel(0, col, brightness)
    # Picior vertical la mijloc (coloana 2, rânduri 1–4)
    for row in range(1, 5):
        hub.display.pixel(row, 2, brightness)


def _signal_lpf2_connected(hub):
    """Doua blink-uri scurte apoi T fix — vizibil ca s-a conectat ESP-ul."""
    for _ in range(2):
        _draw_T(hub, 100)
        wait(350)
        hub.display.off()
        wait(180)
    _draw_T(hub, 100)


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


def _draw_warning_triangle(hub, brightness=100):
    """Triunghi avertizare + ! pe matrice 5x5 (varf sus, baza jos, punct separat de tija).

    Layout (■ = pixel aprins):
      . . ■ . .
      . . ■ . .   tija !
      ■ . . . ■
      ■ . ■ . ■   punct !
      ■ ■ ■ ■ ■   baza
    """
    hub.display.off()
    # Varf triunghi + capat tija exclamarii
    hub.display.pixel(0, 2, brightness)
    hub.display.pixel(1, 2, brightness)
    # Laturi (fara pixel central = spatiu in tija)
    hub.display.pixel(2, 0, brightness)
    hub.display.pixel(2, 4, brightness)
    # Laturi + punct exclamarii (separat de tija)
    hub.display.pixel(3, 0, brightness)
    hub.display.pixel(3, 2, brightness)
    hub.display.pixel(3, 4, brightness)
    # Baza triunghi
    for col in range(5):
        hub.display.pixel(4, col, brightness)


def _arms_home(arm_left, arm_right):
    arm_left.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, 0, then=Stop.HOLD, wait=True)


def _pose_home(arm_left, arm_right, head, *, move_head=True):
    _arms_home(arm_left, arm_right)
    if move_head:
        _head_home(head, wait=True)


def dance_arms_and_wheels(arm_left, arm_right, w_left, w_right, head):
    """Miscare dans: brate + cap + roti fata/spate alternativ."""
    for _ in range(_DANCE_CYCLES):
        arm_left.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        _head_up(head, wait=False)
        w_left.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_DANCE_MS, then=Stop.BRAKE, wait=False)
        w_right.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_DANCE_MS, then=Stop.BRAKE, wait=True)
        arm_left.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        _head_down(head, wait=False)
        w_left.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_DANCE_MS, then=Stop.BRAKE, wait=False)
        w_right.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_DANCE_MS, then=Stop.BRAKE, wait=True)
    _pose_home(arm_left, arm_right, head)


def repose_pose(arm_left, arm_right, head):
    _pose_home(arm_left, arm_right, head)


def left_arm_up_pose(arm_left, arm_right, head):
    arm_left.run_target(_SPEED, _ANGLE_ARM_PATTERN, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    _head_to(head, _HEAD_TILT, wait=True)


def right_arm_up_pose(arm_left, arm_right, head):
    arm_left.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, _ANGLE_ARM_PATTERN, then=Stop.HOLD, wait=False)
    _head_to(head, _HEAD_TILT, wait=True)


def breathe_in_pose(arm_left, arm_right, head):
    arm_left.run_target(_SPEED, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    _head_up(head, wait=True)


def breathe_out_pose(arm_left, arm_right, head):
    arm_left.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    _head_down(head, wait=True)


def breathe_in_with_matrix(arm_left, arm_right, head, hub, total_ms=1200):
    """Inspiratie scurta pentru comanda simpla/follow-pattern: brate + cap + val pe matrice."""
    breathe_in_pose(arm_left, arm_right, head)
    _matrix_wave_inspire(hub, total_ms)
    _matrix_clear(hub)


def emotion_happy_routine(arm_left, arm_right, w_left, w_right, head, hub):
    """Cmd 15 — bucurie: smiley face + dans brate + cap + roti fata/spate."""
    for cycle in range(_DANCE_CYCLES):
        _draw_smiley(hub)
        arm_left.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        _head_up(head, wait=False)
        w_left.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_EMOTION_MS, then=Stop.BRAKE, wait=False)
        w_right.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_EMOTION_MS, then=Stop.BRAKE, wait=True)
        arm_left.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        _head_down(head, wait=False)
        w_left.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_EMOTION_MS, then=Stop.BRAKE, wait=False)
        w_right.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_EMOTION_MS, then=Stop.BRAKE, wait=True)
        if cycle < _DANCE_CYCLES - 1:
            _head_nod(head, times=1)
            wheels_turn_left(w_left, w_right)
            wheels_turn_right(w_left, w_right)
    _pose_home(arm_left, arm_right, head)
    hub.display.off()


def emotion_sad_routine(arm_left, arm_right, head, hub):
    """Cmd 13 — tristete: sad face + brate jos + cap coborat + animatie lacrimi."""
    _draw_sad_face(hub)
    arm_left.run_target(_SPEED // 2, -_ANGLE_SIDE, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED // 2, -_ANGLE_SIDE, then=Stop.HOLD, wait=False)
    _head_down(head, wait=True)
    # Animatie lacrimi: 4 runde, picaturi cad pe col 1 si col 3 (sub ochi)
    for _ in range(4):
        _draw_sad_face(hub)
        wait(400)
        for row in range(2, 5):
            hub.display.pixel(row, 1, 90)   # lacrima stanga
            hub.display.pixel(row, 3, 90)   # lacrima dreapta
            wait(320)
            hub.display.pixel(row, 1, 0)
            hub.display.pixel(row, 3, 0)
    _pose_home(arm_left, arm_right, head)
    hub.display.off()


def emotion_surprised_routine(arm_left, arm_right, head, hub):
    """Cmd 14 — uimire: surprised face + brate sus rapid + cap sus + flash alternant."""
    _draw_surprised_face(hub)
    arm_left.run_target(_SPEED * 2, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED * 2, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    _head_up(head, wait=True)
    # Flash alternant: fata uimita <-> ecran plin, de 4 ori
    for _ in range(4):
        for row in range(5):
            for col in range(5):
                hub.display.pixel(row, col, 100)
        wait(220)
        _draw_surprised_face(hub)
        wait(220)
    wait(600)
    _pose_home(arm_left, arm_right, head)
    hub.display.off()


def emotion_angry_routine(arm_left, arm_right, w_left, w_right, head, hub):
    """Cmd 16 — furie: pumni + cap + mini-cerc (rotatie completa pe loc)."""

    def _draw_angry_brows(drop, b=100):
        # drop 0..2: sprancenele "cad" progresiv peste ochi.
        hub.display.off()
        # Spranceana stanga (diagonala coboratoare spre centru)
        hub.display.pixel(min(4, 0 + drop), 0, b)
        hub.display.pixel(min(4, 0 + drop), 1, b)
        hub.display.pixel(min(4, 1 + drop), 2, b - 15)
        # Spranceana dreapta (simetrica)
        hub.display.pixel(min(4, 0 + drop), 4, b)
        hub.display.pixel(min(4, 0 + drop), 3, b)
        hub.display.pixel(min(4, 1 + drop), 2, b - 15)
        # Gura incruntata
        hub.display.pixel(3, 1, 75)
        hub.display.pixel(3, 2, 55)
        hub.display.pixel(3, 3, 75)

    # Intro: brate "pregatite de pumn"
    arm_left.run_target(_SPEED * 2, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED * 2, -_ANGLE_OPEN, then=Stop.HOLD, wait=False)
    _head_to(head, _HEAD_TILT, wait=True)

    # 3 cicluri: mini-cerc + pumni (cercul e clar vizibil, nu doar un pivot scurt).
    for _ in range(3):
        _mini_circle_left(w_left, w_right)
        for drop in (0, 1, 2):
            _draw_angry_brows(drop)
            arm_left.run_target(_SPEED * 2, _ANGLE_DANCE + _EMOTION_ARM_EXTRA, then=Stop.HOLD, wait=False)
            arm_right.run_target(_SPEED * 2, _ANGLE_DANCE + _EMOTION_ARM_EXTRA, then=Stop.HOLD, wait=False)
            _head_down(head, wait=True)
            wheels_turn_left(w_left, w_right, _ANGRY_PIVOT_MS // 2)
            wait(50)
            arm_left.run_target(_SPEED * 2, -_ANGLE_SIDE, then=Stop.HOLD, wait=False)
            arm_right.run_target(_SPEED * 2, -_ANGLE_SIDE, then=Stop.HOLD, wait=False)
            _head_to(head, _HEAD_TILT, wait=True)
            wait(50)
        # Mic flash de "furie"
        for row in range(5):
            for col in range(5):
                hub.display.pixel(row, col, 95)
        wait(90)
        hub.display.off()
        wait(90)

    wheels_brake(w_left, w_right)
    _pose_home(arm_left, arm_right, head)
    hub.display.off()


def emotion_meltdown_routine(arm_left, arm_right, w_left, w_right, head, hub):
    """Cmd 17 — meltdown: agitatie + triunghi avertizare cu ! pe burta (matrice Hub)."""
    _draw_warning_triangle(hub)
    # Puls: triunghi <-> off (senzatie overload).
    for _ in range(3):
        _draw_warning_triangle(hub, 100)
        wait(120)
        hub.display.off()
        wait(120)

    # 4 cicluri de agitatie: brate sus/jos amplu + pivot dublu + miscari fata/spate.
    meltdown_angle = _ANGLE_DANCE + _EMOTION_ARM_EXTRA
    for _ in range(_DANCE_CYCLES):
        _draw_warning_triangle(hub, 100)
        arm_left.run_target(_SPEED * 2, meltdown_angle, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED * 2, -meltdown_angle, then=Stop.HOLD, wait=False)
        _head_up(head, wait=False)
        wheels_turn_left(w_left, w_right)
        wheels_turn_left(w_left, w_right)
        wheels_turn_right(w_left, w_right)
        wheels_turn_right(w_left, w_right)
        wheels_forward(w_left, w_right)
        wheels_forward(w_left, w_right)
        wheels_backward(w_left, w_right)
        wheels_backward(w_left, w_right)
        arm_left.run_target(_SPEED * 2, -meltdown_angle, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED * 2, meltdown_angle, then=Stop.HOLD, wait=False)
        _head_down(head, wait=False)
        # Flash scurt: triunghi avertizare
        _draw_warning_triangle(hub, 100)
        wait(90)
        hub.display.off()
        wait(90)

    wheels_brake(w_left, w_right)
    _pose_home(arm_left, arm_right, head)
    hub.display.off()


def breathing_show_routine(arm_left, arm_right, head, hub):
    """PAS 4 — ~10s: brațe + cap + matrix; sunet inspir/expir doar PCM pe ESP dacă uplodat."""
    inh_ms = _BSHOW_INH_MS
    exh_ms = _BSHOW_EXH_MS
    n = _BSHOW_CYCLES
    _matrix_clear(hub)
    for k in range(n):
        print("Breathing show", k + 1, "/", n)
        breathe_in_pose(arm_left, arm_right, head)
        _matrix_wave_inspire(hub, inh_ms)
        breathe_out_pose(arm_left, arm_right, head)
        _matrix_wave_expire(hub, exh_ms)
    _matrix_clear(hub)
    print("Breathing show end")


def wheels_forward(w_left, w_right):
    w_left.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=False)
    w_right.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=True)


def wheels_backward(w_left, w_right):
    w_left.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=False)
    w_right.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=True)


def wheels_turn_left(w_left, w_right, pivot_ms=None):
    ms = _WHEEL_PIVOT_MS if pivot_ms is None else pivot_ms
    w_left.run_time(-_WHEEL_PIVOT_SPEED, ms, then=Stop.BRAKE, wait=False)
    w_right.run_time(_WHEEL_PIVOT_SPEED, ms, then=Stop.BRAKE, wait=True)


def wheels_turn_right(w_left, w_right, pivot_ms=None):
    ms = _WHEEL_PIVOT_MS if pivot_ms is None else pivot_ms
    w_left.run_time(_WHEEL_PIVOT_SPEED, ms, then=Stop.BRAKE, wait=False)
    w_right.run_time(-_WHEEL_PIVOT_SPEED, ms, then=Stop.BRAKE, wait=True)


def _mini_circle_left(w_left, w_right, *, steps=_ANGRY_CIRCLE_STEPS, pivot_ms=_ANGRY_PIVOT_MS):
    """~360° pe loc: steps pivot-uri scurte consecutive."""
    for _ in range(steps):
        wheels_turn_left(w_left, w_right, pivot_ms)


def wheels_brake(w_left, w_right):
    w_left.stop()
    w_right.stop()


def run_cmd(arm_left, arm_right, w_left, w_right, head, hub, code):
    simple_cmd = False
    if code == 1:
        print("Dance!")
        dance_arms_and_wheels(arm_left, arm_right, w_left, w_right, head)
    elif code == 2:
        print("Repose")
        repose_pose(arm_left, arm_right, head)
        simple_cmd = True
    elif code == 3:
        print("Left arm")
        left_arm_up_pose(arm_left, arm_right, head)
        simple_cmd = True
    elif code == 4:
        print("Right arm")
        right_arm_up_pose(arm_left, arm_right, head)
        simple_cmd = True
    elif code == 5:
        print("Breathe in")
        breathe_in_with_matrix(arm_left, arm_right, head, hub)
        simple_cmd = True
    elif code == 6:
        print("Breathe out")
        breathe_out_pose(arm_left, arm_right, head)
        simple_cmd = True
    elif code == 7:
        print("Drive FWD")
        _head_to(head, _HEAD_TILT, wait=False)
        wheels_forward(w_left, w_right)
        simple_cmd = True
    elif code == 8:
        print("Drive back")
        _head_down(head, wait=False)
        wheels_backward(w_left, w_right)
        simple_cmd = True
    elif code == 9:
        print("Turn L")
        _head_to(head, _HEAD_TILT, wait=False)
        wheels_turn_left(w_left, w_right)
        simple_cmd = True
    elif code == 10:
        print("Turn R")
        _head_to(head, _HEAD_TILT, wait=False)
        wheels_turn_right(w_left, w_right)
        simple_cmd = True
    elif code == 11:
        print("Wheels stop")
        wheels_brake(w_left, w_right)
        simple_cmd = True
    elif code == 12:
        print("Breathing SHOW")
        breathing_show_routine(arm_left, arm_right, head, hub)
    elif code == 13:
        print("Emotion SAD")
        emotion_sad_routine(arm_left, arm_right, head, hub)
    elif code == 14:
        print("Emotion SURPRISED")
        emotion_surprised_routine(arm_left, arm_right, head, hub)
    elif code == 15:
        print("Emotion HAPPY")
        emotion_happy_routine(arm_left, arm_right, w_left, w_right, head, hub)
    elif code == 16:
        print("Emotion ANGRY")
        emotion_angry_routine(arm_left, arm_right, w_left, w_right, head, hub)
    elif code == 17:
        print("Emotion MELTDOWN")
        emotion_meltdown_routine(arm_left, arm_right, w_left, w_right, head, hub)
    else:
        pass

    if simple_cmd:
        wait(350)
        _arms_home(arm_left, arm_right)
    if code != 0:
        _draw_T(hub)


def main():
    hub = PrimeHub()

    arm_left = Motor(ARM_LEFT_PORT)
    arm_right = Motor(ARM_RIGHT_PORT, positive_direction=Direction.COUNTERCLOCKWISE)
    wheel_left = Motor(WHEEL_LEFT_PORT)
    wheel_right = Motor(WHEEL_RIGHT_PORT, positive_direction=Direction.COUNTERCLOCKWISE)
    head = Motor(HEAD_PORT)

    while True:
        # (Re)initializare PupRemote — daca ESP se deconecteaza, refacem canalele.
        try:
            pr = PUPRemoteHub(SENSOR_PORT, max_packet_size=16)
            pr.add_channel("obj", to_hub_fmt="b")
            pr.add_channel("cmd", to_hub_fmt="b")
            print("LPF2 init OK — astept comenzi")
            _signal_lpf2_connected(hub)
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
                    run_cmd(arm_left, arm_right, wheel_left, wheel_right, head, hub, cmd_val)

                last_cmd = cmd_val
                wait(LOOP_DELAY_MS)
        except OSError as e:
            print("LPF2 pierdut:", e, "— reconectez...")
            wait(1000)


main()
