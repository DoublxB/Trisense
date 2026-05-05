# -*- coding: utf-8 -*-
"""
Masina de stari TriSense 3.0:
START -> SALUT (ID 1) -> SELECTIE_JOC -> ACTIVITATE (ID 2+) -> FINAL
"""

from __future__ import annotations

from enum import Enum, auto


class RobotState(Enum):
    START = auto()
    SALUT = auto()          # recunoastere fata / ID 1
    SELECTIE_JOC = auto()
    ACTIVITATE = auto()     # constructii LEGO / ID 2+
    FINAL = auto()          # recompensa / inchidere runda
    GUESS_EMOTION = auto()  # Act. 6: asteapta ghicirea emotiei
    FOLLOW_PATTERN = auto() # Act. 7: asteapta replicarea pasului curent


# Semantica ID (HuskyLens Object Classification pe ESP32; clase invatate pe senzor):
# ID 1 = fata utilizatorului (clasa 1 invatata)
# ID 2+ = piese / constructii LEGO (clase invatate, fara stickere)


def describe_id(vision_id: int) -> str:
    if vision_id == 1:
        return "fata"
    if vision_id >= 2:
        return "lego"
    return "necunoscut"
