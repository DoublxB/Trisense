"""
TriSense - Program Pybricks pentru Hub SPIKE Prime.
Ruleaza pe Hub; brate Port B+E, roti Port C+D.

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
  18  build model tinta TURN (Build the Model / Hanoi): coloana verticala pe matrice, ramane afisat
  19  build model tinta LINIE: rand orizontal de 3 pe matrice, ramane afisat
  20  build model tinta L: forma L pe matrice, ramane afisat
  21  Stop&Go GO (1): cifra 1 + lumina verde (~3.5s)
  22  Stop&Go FREEZE (0): cifra 0 + lumina rosie (~3.5s)
  23  Stop&Go END: stinge lumina, redeseneaza T

Montaj fizic diferit → poti folosi invertire pe un Motor sau schimba C/D sus/jos.

La handshake cu ESP (LPF2 OK), Hub afiseaza litera „T” mare pe matrice (TriSense).

PAS 4 Pe PC: ghid vocal Audio TCP (PCM de pe laptop); MQTT doar action breathing_show — fără speak pe ESP/Gemini.
"""

from pybricks.hubs import PrimeHub
from pybricks.pupdevices import Motor
from pybricks.parameters import Port, Direction, Stop, Button, Color
from pybricks.tools import wait
from pupremote_hub import PUPRemoteHub

# Portul unde e conectat cablul LEGO (LMS-ESP32)
SENSOR_PORT = Port.A
LOOP_DELAY_MS = 50

_PR = None
_PULSE_MS = 80

ARM_LEFT_PORT = Port.B
ARM_RIGHT_PORT = Port.E
WHEEL_LEFT_PORT = Port.C
WHEEL_RIGHT_PORT = Port.D

_SPEED = 380
_WHEEL_SPEED_DEG_S = 240
_WHEEL_MS = 700
_ANGLE_DANCE = 55
_ANGLE_SIDE = 40
_ANGLE_OPEN = 50
# Cmd 3–4 (brat sus stanga/dreapta): unghi clar dar usor.
_ANGLE_ARM_PATTERN = 52
# Pivot pe loc (cmd 9–10): rotatie scurta.
_WHEEL_PIVOT_SPEED = 200
_WHEEL_PIVOT_MS = 600
_WHEEL_DANCE_MS = 600
_WHEEL_EMOTION_MS = 800
_DANCE_CYCLES = 3
_EMOTION_ARM_EXTRA = 20
# Angry: pivot scurt.
_ANGRY_PIVOT_MS = 700
_ANGRY_CIRCLE_STEPS = 3

# Aceleași timing-uri ca BV + PCM inspir/expir în main_robot. `_BSHOW_CYCLES` = `_BV_BREATHING_CYCLES`.
_BSHOW_CYCLES = 2
_BSHOW_INH_MS = 2500
_BSHOW_EXH_MS = 2500


def _matrix_clear(hub):
    try:
        hub.display.off()
    except Exception:
        pass


def _pulse_lpf2():
    """Un pas de heartbeat LPF2: face un pr.call() scurt; ignora orice eroare."""
    global _PR
    if _PR is None:
        return
    try:
        _PR.call("cmd")
    except Exception:
        pass


def _pulse_wait(ms):
    """wait() lung impartit in pasi de _PULSE_MS cu pr.call() intre ei => LPF2 ramane viu."""
    if ms <= 0:
        return
    remaining = int(ms)
    step = _PULSE_MS
    while remaining > step:
        wait(step)
        _pulse_lpf2()
        remaining -= step
    if remaining > 0:
        wait(remaining)
        _pulse_lpf2()


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
        _pulse_wait(step)


def _matrix_wave_expire(hub, total_ms):
    """Stinge de sus în jos (~expiratie)."""
    step = max(total_ms // 5, 40)
    for row in range(5):
        for col in range(5):
            try:
                hub.display.pixel(row, col, 0)
            except Exception:
                pass
        _pulse_wait(step)


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


def _draw_digit_1(hub, brightness=100):
    """Cifra 1 pe matrice 5x5 (Stop & Go GO)."""
    hub.display.off()
    for row in range(5):
        hub.display.pixel(row, 2, brightness)


def _draw_digit_0(hub, brightness=100):
    """Cifra 0 pe matrice 5x5 (Stop & Go FREEZE)."""
    hub.display.off()
    for col in range(5):
        hub.display.pixel(0, col, brightness)
        hub.display.pixel(4, col, brightness)
    for row in range(1, 4):
        hub.display.pixel(row, 0, brightness)
        hub.display.pixel(row, 4, brightness)


def _draw_build_tower(hub, brightness=90):
    """Build the Model nivel 1 — turn dreptunghiular (4 caramizi 2x4 portocalii stivuite).

    Profil din fata pe 5x5:
      . X X X .
      . X X X .
      . X X X .
      . X X X .
      . . . . .
    """
    hub.display.off()
    for row in (0, 1, 2, 3):
        for col in (1, 2, 3):
            hub.display.pixel(row, col, brightness)


def _draw_build_pyramid(hub, brightness=90):
    """Build the Model nivel 2 — piramida albastra in trepte (2 baze, 1 mijloc, 1 varf 2x2).

    Profil din fata pe 5x5:
      . . X . .   <- 2x2 varf
      . X X X .   <- 2x4 mijloc
      X X X X X   <- 2x (2x4) baza
      . . . . .
      . . . . .
    """
    hub.display.off()
    # baza (rand 2): toata latimea
    for col in range(5):
        hub.display.pixel(2, col, brightness)
    # mijloc (rand 1): 3 coloane
    for col in (1, 2, 3):
        hub.display.pixel(1, col, brightness)
    # varf (rand 0): 1 coloana centrala
    hub.display.pixel(0, 2, brightness)


def _draw_build_robot(hub, brightness=90):
    """Build the Model nivel 3 — robot negru in cruce (baza, gat, brate 2x6, cap 2x2).

    Profil din fata pe 5x5:
      . . X . .   <- cap (2x2)
      X X X X X   <- brate (2x6)
      . . X . .   <- gat (2x2)
      . X X X .   <- baza strat 2 (2x4)
      . X X X .   <- baza strat 1 (2x4)
    """
    hub.display.off()
    # cap (rand 0): centru
    hub.display.pixel(0, 2, brightness)
    # brate (rand 1): toata latimea
    for col in range(5):
        hub.display.pixel(1, col, brightness)
    # gat (rand 2): centru
    hub.display.pixel(2, 2, brightness)
    # baza 2 straturi (randuri 3 si 4): 3 coloane
    for row in (3, 4):
        for col in (1, 2, 3):
            hub.display.pixel(row, col, brightness)


_ARM_MOVE_MS = 350


def _arms_home(arm_left, arm_right):
    """Revino la 0° (pozitia de repaus) si asteapta finalizarea, cu LPF2 activ."""
    arm_left.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    for _ in range(20):
        try:
            if arm_left.done() and arm_right.done():
                break
        except Exception:
            break
        _pulse_wait(80)


def _pose_home(arm_left, arm_right):
    _arms_home(arm_left, arm_right)


def dance_arms_and_wheels(arm_left, arm_right, w_left, w_right):
    """Miscare dans: brate + roti fata/spate alternativ."""
    for _ in range(_DANCE_CYCLES):
        arm_left.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        w_left.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_DANCE_MS, then=Stop.BRAKE, wait=False)
        w_right.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_DANCE_MS, then=Stop.BRAKE, wait=False)
        _pulse_wait(_WHEEL_DANCE_MS)
        arm_left.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        w_left.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_DANCE_MS, then=Stop.BRAKE, wait=False)
        w_right.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_DANCE_MS, then=Stop.BRAKE, wait=False)
        _pulse_wait(_WHEEL_DANCE_MS)
    _pose_home(arm_left, arm_right)


def repose_pose(arm_left, arm_right):
    _pose_home(arm_left, arm_right)


def left_arm_up_pose(arm_left, arm_right):
    arm_left.run_target(_SPEED, _ANGLE_ARM_PATTERN, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    _pulse_wait(_ARM_MOVE_MS)


def right_arm_up_pose(arm_left, arm_right):
    arm_left.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, _ANGLE_ARM_PATTERN, then=Stop.HOLD, wait=False)
    _pulse_wait(_ARM_MOVE_MS)


def breathe_in_pose(arm_left, arm_right):
    arm_left.run_target(_SPEED, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    _pulse_wait(_ARM_MOVE_MS)


def breathe_out_pose(arm_left, arm_right):
    arm_left.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    arm_right.run_target(_SPEED, 0, then=Stop.HOLD, wait=False)
    _pulse_wait(_ARM_MOVE_MS)


def breathe_in_with_matrix(arm_left, arm_right, hub, total_ms=1200):
    """Inspiratie scurta pentru comanda simpla/follow-pattern: brate + val pe matrice."""
    breathe_in_pose(arm_left, arm_right)
    _matrix_wave_inspire(hub, total_ms)
    _matrix_clear(hub)


def emotion_happy_routine(arm_left, arm_right, w_left, w_right, hub):
    """Cmd 15 — bucurie: smiley + dans brate alternativ + roti fata/spate + sarituri + pivot."""
    for cycle in range(_DANCE_CYCLES):
        _draw_smiley(hub)
        arm_left.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        w_left.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_EMOTION_MS, then=Stop.BRAKE, wait=False)
        w_right.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_EMOTION_MS, then=Stop.BRAKE, wait=False)
        _pulse_wait(_WHEEL_EMOTION_MS)
        arm_left.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        _pulse_wait(220)
        arm_left.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, _ANGLE_DANCE, then=Stop.HOLD, wait=False)
        _pulse_wait(220)
        arm_left.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        arm_right.run_target(_SPEED, -_ANGLE_DANCE, then=Stop.HOLD, wait=False)
        w_left.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_EMOTION_MS, then=Stop.BRAKE, wait=False)
        w_right.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_EMOTION_MS, then=Stop.BRAKE, wait=False)
        _pulse_wait(_WHEEL_EMOTION_MS)
        if cycle < _DANCE_CYCLES - 1:
            wheels_turn_left(w_left, w_right)
            wheels_turn_right(w_left, w_right)
    _pose_home(arm_left, arm_right)
    hub.display.off()


def emotion_sad_routine(arm_left, arm_right, hub):
    """Cmd 13 — tristete: sad face + brate jos lent + animatie lacrimi + tremurat slab."""
    _draw_sad_face(hub)
    slow = _SPEED // 2
    arm_left.run_target(slow, -_ANGLE_SIDE, then=Stop.HOLD, wait=False)
    arm_right.run_target(slow, -_ANGLE_SIDE, then=Stop.HOLD, wait=False)
    _pulse_wait(_ARM_MOVE_MS)
    for cycle in range(4):
        _draw_sad_face(hub)
        _pulse_wait(400)
        for row in range(2, 5):
            hub.display.pixel(row, 1, 90)
            hub.display.pixel(row, 3, 90)
            _pulse_wait(280)
            hub.display.pixel(row, 1, 0)
            hub.display.pixel(row, 3, 0)
        if cycle < 3:
            arm_left.run_target(slow, -_ANGLE_SIDE + 10, then=Stop.HOLD, wait=False)
            arm_right.run_target(slow, -_ANGLE_SIDE + 10, then=Stop.HOLD, wait=False)
            _pulse_wait(300)
            arm_left.run_target(slow, -_ANGLE_SIDE, then=Stop.HOLD, wait=False)
            arm_right.run_target(slow, -_ANGLE_SIDE, then=Stop.HOLD, wait=False)
            _pulse_wait(300)
    _pose_home(arm_left, arm_right)
    hub.display.off()


def emotion_surprised_routine(arm_left, arm_right, hub):
    """Cmd 14 — uimire: brate jerk sus/jos + flash alternant."""
    fast = min(_SPEED * 2, 600)
    _draw_surprised_face(hub)
    arm_left.run_target(fast, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    arm_right.run_target(fast, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    _pulse_wait(300)
    for _ in range(4):
        for row in range(5):
            for col in range(5):
                hub.display.pixel(row, col, 100)
        arm_left.run_target(fast, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
        arm_right.run_target(fast, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
        _pulse_wait(220)
        _draw_surprised_face(hub)
        arm_left.run_target(fast, _ANGLE_OPEN - 25, then=Stop.HOLD, wait=False)
        arm_right.run_target(fast, _ANGLE_OPEN - 25, then=Stop.HOLD, wait=False)
        _pulse_wait(220)
    arm_left.run_target(fast, 0, then=Stop.HOLD, wait=False)
    arm_right.run_target(fast, 0, then=Stop.HOLD, wait=False)
    for row in range(5):
        for col in range(5):
            hub.display.pixel(row, col, 100)
    _pulse_wait(400)
    _pose_home(arm_left, arm_right)
    hub.display.off()


def emotion_angry_routine(arm_left, arm_right, w_left, w_right, hub):
    """Cmd 16 — furie: pumni + mini-cerc."""

    def _draw_angry_brows(drop, b=100):
        hub.display.off()
        hub.display.pixel(min(4, 0 + drop), 0, b)
        hub.display.pixel(min(4, 0 + drop), 1, b)
        hub.display.pixel(min(4, 1 + drop), 2, b - 15)
        hub.display.pixel(min(4, 0 + drop), 4, b)
        hub.display.pixel(min(4, 0 + drop), 3, b)
        hub.display.pixel(min(4, 1 + drop), 2, b - 15)
        hub.display.pixel(3, 1, 75)
        hub.display.pixel(3, 2, 55)
        hub.display.pixel(3, 3, 75)

    fast = min(_SPEED * 2, 600)
    arm_left.run_target(fast, _ANGLE_OPEN, then=Stop.HOLD, wait=False)
    arm_right.run_target(fast, -_ANGLE_OPEN, then=Stop.HOLD, wait=False)
    _pulse_wait(_ARM_MOVE_MS)

    for _ in range(3):
        _mini_circle_left(w_left, w_right)
        for drop in (0, 1, 2):
            _draw_angry_brows(drop)
            arm_left.run_target(fast, _ANGLE_DANCE + _EMOTION_ARM_EXTRA, then=Stop.HOLD, wait=False)
            arm_right.run_target(fast, _ANGLE_DANCE + _EMOTION_ARM_EXTRA, then=Stop.HOLD, wait=False)
            wheels_turn_left(w_left, w_right, _ANGRY_PIVOT_MS // 2)
            _pulse_wait(50)
            arm_left.run_target(fast, -_ANGLE_SIDE, then=Stop.HOLD, wait=False)
            arm_right.run_target(fast, -_ANGLE_SIDE, then=Stop.HOLD, wait=False)
            _pulse_wait(_ARM_MOVE_MS // 2)
            _pulse_wait(50)
        for row in range(5):
            for col in range(5):
                hub.display.pixel(row, col, 95)
        _pulse_wait(90)
        hub.display.off()
        _pulse_wait(90)

    wheels_brake(w_left, w_right)
    _pose_home(arm_left, arm_right)
    hub.display.off()


def emotion_meltdown_routine(arm_left, arm_right, w_left, w_right, hub):
    """Cmd 17 — meltdown: agitatie + triunghi avertizare cu ! pe burta (matrice Hub)."""
    _draw_warning_triangle(hub)
    for _ in range(3):
        _draw_warning_triangle(hub, 100)
        _pulse_wait(120)
        hub.display.off()
        _pulse_wait(120)

    fast = min(_SPEED * 2, 600)
    meltdown_angle = _ANGLE_DANCE + _EMOTION_ARM_EXTRA
    for _ in range(_DANCE_CYCLES):
        _draw_warning_triangle(hub, 100)
        arm_left.run_target(fast, meltdown_angle, then=Stop.HOLD, wait=False)
        arm_right.run_target(fast, -meltdown_angle, then=Stop.HOLD, wait=False)
        wheels_turn_left(w_left, w_right)
        arm_left.run_target(fast, 0, then=Stop.HOLD, wait=False)
        arm_right.run_target(fast, 0, then=Stop.HOLD, wait=False)
        _pulse_wait(150)
        arm_left.run_target(fast, meltdown_angle, then=Stop.HOLD, wait=False)
        arm_right.run_target(fast, meltdown_angle, then=Stop.HOLD, wait=False)
        wheels_turn_right(w_left, w_right)
        arm_left.run_target(fast, -meltdown_angle, then=Stop.HOLD, wait=False)
        arm_right.run_target(fast, -meltdown_angle, then=Stop.HOLD, wait=False)
        wheels_forward(w_left, w_right)
        arm_left.run_target(fast, -meltdown_angle, then=Stop.HOLD, wait=False)
        arm_right.run_target(fast, meltdown_angle, then=Stop.HOLD, wait=False)
        wheels_backward(w_left, w_right)
        _draw_warning_triangle(hub, 100)
        _pulse_wait(90)
        hub.display.off()
        _pulse_wait(90)

    wheels_brake(w_left, w_right)
    _pose_home(arm_left, arm_right)
    hub.display.off()


def breathing_show_routine(arm_left, arm_right, hub):
    """PAS 4 — ~10s: brațe + matrix inspir/expir."""
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
    _pose_home(arm_left, arm_right)
    print("Breathing show end")


def wheels_forward(w_left, w_right):
    w_left.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=False)
    w_right.run_time(_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=False)
    _pulse_wait(_WHEEL_MS)


def wheels_backward(w_left, w_right):
    w_left.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=False)
    w_right.run_time(-_WHEEL_SPEED_DEG_S, _WHEEL_MS, then=Stop.BRAKE, wait=False)
    _pulse_wait(_WHEEL_MS)


def wheels_turn_left(w_left, w_right, pivot_ms=None):
    ms = _WHEEL_PIVOT_MS if pivot_ms is None else pivot_ms
    w_left.run_time(-_WHEEL_PIVOT_SPEED, ms, then=Stop.BRAKE, wait=False)
    w_right.run_time(_WHEEL_PIVOT_SPEED, ms, then=Stop.BRAKE, wait=False)
    _pulse_wait(ms)


def wheels_turn_right(w_left, w_right, pivot_ms=None):
    ms = _WHEEL_PIVOT_MS if pivot_ms is None else pivot_ms
    w_left.run_time(_WHEEL_PIVOT_SPEED, ms, then=Stop.BRAKE, wait=False)
    w_right.run_time(-_WHEEL_PIVOT_SPEED, ms, then=Stop.BRAKE, wait=False)
    _pulse_wait(ms)


def _mini_circle_left(w_left, w_right, *, steps=_ANGRY_CIRCLE_STEPS, pivot_ms=_ANGRY_PIVOT_MS):
    """~360° pe loc: steps pivot-uri scurte consecutive."""
    for _ in range(steps):
        wheels_turn_left(w_left, w_right, pivot_ms)


def wheels_brake(w_left, w_right):
    w_left.stop()
    w_right.stop()


def run_cmd(arm_left, arm_right, w_left, w_right, hub, code):
    simple_cmd = False
    keep_display = False
    if code == 1:
        print("Dance!")
        dance_arms_and_wheels(arm_left, arm_right, w_left, w_right)
    elif code == 2:
        print("Repose")
        repose_pose(arm_left, arm_right)
        simple_cmd = True
    elif code == 3:
        print("Left arm")
        left_arm_up_pose(arm_left, arm_right)
        simple_cmd = True
    elif code == 4:
        print("Right arm")
        right_arm_up_pose(arm_left, arm_right)
        simple_cmd = True
    elif code == 5:
        print("Breathe in")
        breathe_in_with_matrix(arm_left, arm_right, hub)
        simple_cmd = True
    elif code == 6:
        print("Breathe out")
        breathe_out_pose(arm_left, arm_right)
        simple_cmd = True
    elif code == 7:
        print("Drive FWD")
        wheels_forward(w_left, w_right)
        simple_cmd = True
    elif code == 8:
        print("Drive back")
        wheels_backward(w_left, w_right)
        simple_cmd = True
    elif code == 9:
        print("Turn L")
        wheels_turn_left(w_left, w_right)
        simple_cmd = True
    elif code == 10:
        print("Turn R")
        wheels_turn_right(w_left, w_right)
        simple_cmd = True
    elif code == 11:
        print("Wheels stop")
        wheels_brake(w_left, w_right)
        simple_cmd = True
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
    elif code == 16:
        print("Emotion ANGRY")
        emotion_angry_routine(arm_left, arm_right, w_left, w_right, hub)
    elif code == 17:
        print("Emotion MELTDOWN")
        emotion_meltdown_routine(arm_left, arm_right, w_left, w_right, hub)
    elif code == 18:
        print("Build model: TOWER")
        _draw_build_tower(hub)
        keep_display = True
    elif code == 19:
        print("Build model: PYRAMID")
        _draw_build_pyramid(hub)
        keep_display = True
    elif code == 20:
        print("Build model: ROBOT")
        _draw_build_robot(hub)
        keep_display = True
    elif code == 21:
        print("Stop&Go GO (1)")
        _draw_digit_1(hub, 100)
        try:
            hub.light.on(Color.GREEN)
        except Exception:
            pass
        _pulse_wait(3500)
        try:
            hub.light.off()
        except Exception:
            pass
    elif code == 22:
        print("Stop&Go FREEZE (0)")
        _draw_digit_0(hub, 100)
        try:
            hub.light.on(Color.RED)
        except Exception:
            pass
        _pulse_wait(3500)
        try:
            hub.light.off()
        except Exception:
            pass
    elif code == 23:
        print("Stop&Go END")
        try:
            hub.light.off()
        except Exception:
            pass
        simple_cmd = True
    else:
        pass

    if simple_cmd:
        _pulse_wait(350)

    # Build the Model: lasam modelul tinta pe matrice ca sa-l copieze copilul.
    if keep_display:
        return

    if code != 0:
        _draw_T(hub)
        _pose_home(arm_left, arm_right)


def main():
    hub = PrimeHub()

    arm_left = Motor(ARM_LEFT_PORT)
    arm_right = Motor(ARM_RIGHT_PORT, positive_direction=Direction.COUNTERCLOCKWISE)
    wheel_left = Motor(WHEEL_LEFT_PORT)
    wheel_right = Motor(WHEEL_RIGHT_PORT, positive_direction=Direction.COUNTERCLOCKWISE)

    global _PR
    while True:
        # (Re)initializare PupRemote — daca ESP se deconecteaza, refacem canalele.
        try:
            pr = PUPRemoteHub(SENSOR_PORT, max_packet_size=16)
            pr.add_channel("obj", to_hub_fmt="b")
            pr.add_channel("cmd", to_hub_fmt="b")
            # Buton Hub -> ESP (acelasi canal ca in main_robot.py, aceeasi ordine).
            pr.add_command("btn", from_hub_fmt="b")
            _PR = pr
            print("LPF2 init OK — astept comenzi")
            _signal_lpf2_connected(hub)
        except OSError as e:
            _PR = None
            print("LPF2 init err:", e, "— retry 2s")
            wait(2000)
            continue

        last_cmd = 0
        last_buttons = ()

        try:
            while True:
                obj = pr.call("obj")
                if obj and obj > 0:
                    print("Obiect detectat ID:", obj)

                # Butoane Hub -> ESP: stanga=listen (voce), dreapta=captura CAM (Build the Model).
                try:
                    pressed = hub.buttons.pressed()
                except Exception:
                    pressed = ()
                if Button.LEFT in pressed and Button.LEFT not in last_buttons:
                    try:
                        pr.call("btn", 1)
                        print("Buton STANGA -> ESP (listen)")
                    except Exception as be:
                        print("btn stanga err:", be)
                if Button.RIGHT in pressed and Button.RIGHT not in last_buttons:
                    try:
                        pr.call("btn", 2)
                        print("Buton DREAPTA -> ESP (captura CAM)")
                    except Exception as be:
                        print("btn dreapta err:", be)
                last_buttons = pressed

                cmd = pr.call("cmd")
                cmd_val = cmd if isinstance(cmd, int) else 0
                if cmd_val < 0 or cmd_val > 255:
                    cmd_val = 0

                if cmd_val != 0 and cmd_val != last_cmd:
                    try:
                        run_cmd(arm_left, arm_right, wheel_left, wheel_right, hub, cmd_val)
                    except Exception as e:
                        print("run_cmd eroare cmd=", cmd_val, ":", e)
                        try:
                            _arms_home(arm_left, arm_right)
                        except Exception:
                            pass
                        try:
                            _draw_T(hub)
                        except Exception:
                            pass

                last_cmd = cmd_val
                wait(LOOP_DELAY_MS)
        except OSError as e:
            print("LPF2 pierdut:", e, "— reconectez...")
            _PR = None
            wait(1000)


main()
