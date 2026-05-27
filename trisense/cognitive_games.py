# -*- coding: utf-8 -*-
"""Date si validari pentru jocuri cognitive 3.11–3.18."""

from __future__ import annotations

import random
import re
from typing import Any, Optional

# 3.11 N-Back — cuvinte scurte pentru copii
NBACK_WORDS = (
    "ball", "cat", "dog", "sun", "tree", "fish", "book", "star", "cup", "hat",
)

# 3.12 Categorii fluenta semantica
CATEGORY_WORDS: dict[str, set[str]] = {
    "animals": {
        "dog", "cat", "bird", "fish", "horse", "cow", "pig", "duck", "lion", "bear",
        "rabbit", "mouse", "frog", "sheep", "chicken", "elephant", "tiger", "monkey",
    },
    "colors": {
        "red", "blue", "green", "yellow", "orange", "purple", "pink", "black", "white", "brown",
    },
    "fruits": {
        "apple", "banana", "orange", "grape", "pear", "peach", "melon", "berry", "mango", "lemon",
    },
}

# 3.14 Stroop — cifra pe matrice = culoare
STROOP_DIGIT_COLOR = {1: "red", 2: "green", 3: "blue"}
STROOP_COLOR_DIGIT = {v: k for k, v in STROOP_DIGIT_COLOR.items()}

# 3.17 Prosody — propozitii cu continut emotional (TTS nu e expresiv; textul sugereaza tonul)
PROSODY_TRIALS: list[tuple[str, str]] = [
    ("happy", "Wow! What a wonderful sunny day! I feel so great!"),
    ("sad", "I lost my favorite toy today. I feel really down."),
    ("angry", "That is not fair at all! I am so upset!"),
    ("calm", "Let's breathe slowly together. Everything is peaceful."),
]

# 3.18 Povesti — (eveniment scurt, ordine corecta 0,1,2)
STORY_SETS: list[list[str]] = [
    ["We wake up.", "We eat breakfast.", "We go to school."],
    ["The seed is planted.", "The flower grows.", "We pick the flower."],
    ["We put on shoes.", "We open the door.", "We walk outside."],
    ["Mix the flour.", "Bake the cake.", "Eat the cake."],
]

# Poveste co-construita — deschideri fallback (fara Gemini)
CO_STORY_OPENINGS: list[str] = [
    "Once upon a time, a little fox found a glowing key. What do you think the key opens, {name}?",
    "On a rainy day, a brave turtle built a tiny boat. Where should the turtle sail, {name}?",
    "In a quiet forest, a robot friend heard a soft song. Who is singing the song, {name}?",
]

_EMOTION_VOCAB: set[str] = {
    "happy", "sad", "angry", "scared", "afraid", "excited", "proud", "lonely", "calm",
    "worried", "brave", "kind", "love", "loved", "fun", "funny", "surprised", "tired",
    "glad", "upset", "joy", "fear", "hope", "peaceful", "nervous", "shy",
}

_STOPWORDS: set[str] = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "on", "at", "it", "i", "we", "you", "he", "she", "they", "my",
    "your", "his", "her", "our", "their", "this", "that", "then", "so", "very", "just",
}


def _content_words(text: str) -> set[str]:
    return {w for w in _norm_words(text) if w not in _STOPWORDS and len(w) > 2}


def analyze_co_story_turn(
    child_line: str,
    *,
    story_vocab: set[str],
    prev_child: str = "",
) -> dict[str, Any]:
    """Metrici locale per rand al copilului in povestea co-construita."""
    words = _content_words(child_line)
    emotion_hits = sorted(w for w in words if w in _EMOTION_VOCAB)
    new_ideas = sorted(w for w in words if w not in story_vocab)
    initiation = bool(new_ideas)
    prev_words = _content_words(prev_child)
    if prev_words and words:
        overlap = len(words & prev_words) / max(1, len(words | prev_words))
        topic_maintained = overlap >= 0.12
    else:
        topic_maintained = True
    return {
        "emotion_words": emotion_hits,
        "emotion_count": len(emotion_hits),
        "initiation": initiation,
        "new_ideas": new_ideas[:6],
        "topic_maintained": topic_maintained,
        "word_count": len(_norm_words(child_line)),
    }


def _norm_words(text: str) -> list[str]:
    t = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return [w for w in t.split() if len(w) > 1]


def build_nback_sequence(level: int = 1, length: int = 6) -> list[str]:
    """Genereaza secventa cu ~30% target-uri n-back."""
    level = max(1, min(level, 2))
    length = max(level + 2, min(length, 8))
    pool = list(NBACK_WORDS)
    seq: list[str] = []
    for i in range(length):
        if i >= level and random.random() < 0.35:
            seq.append(seq[i - level])
        else:
            w = random.choice(pool)
            while i >= level and w == seq[i - level]:
                w = random.choice(pool)
            seq.append(w)
    return seq


def nback_should_yes(seq: list[str], index: int, level: int) -> bool:
    if index < level:
        return False
    return seq[index] == seq[index - level]


def parse_yes_no(transcript: str) -> Optional[bool]:
    bl = (transcript or "").lower()
    if any(k in bl for k in ("yes", "yeah", "yep", "da", "correct", "match")):
        return True
    if any(k in bl for k in ("no", "nope", "not", "nu", "wrong")):
        return False
    return None


def parse_color(transcript: str) -> Optional[str]:
    bl = (transcript or "").lower()
    for c in ("red", "green", "blue"):
        if c in bl:
            return c
    ro = {"rosu": "red", "verde": "green", "albastru": "blue"}
    for k, v in ro.items():
        if k in bl:
            return v
    return None


def parse_emotion_label(transcript: str) -> Optional[str]:
    bl = (transcript or "").lower()
    if any(k in bl for k in ("happy", "glad", "joy", "fericit", "bucuros")):
        return "happy"
    if any(k in bl for k in ("sad", "unhappy", "trist", "down")):
        return "sad"
    if any(k in bl for k in ("angry", "mad", "upset", "furios", "nervos")):
        return "angry"
    if any(k in bl for k in ("calm", "peace", "relax", "linistit")):
        return "calm"
    return None


def count_category_words(transcript: str, category: str) -> dict[str, Any]:
    """Numara cuvinte valide si repetari intr-o categorie."""
    cat = category.lower().strip()
    allowed = CATEGORY_WORDS.get(cat, set())
    words = _norm_words(transcript)
    valid: list[str] = []
    seen: set[str] = set()
    repeats = 0
    for w in words:
        if w not in allowed:
            continue
        if w in seen:
            repeats += 1
        else:
            seen.add(w)
            valid.append(w)
    return {
        "category": cat,
        "valid_count": len(valid),
        "valid_words": valid,
        "repetition_count": repeats,
    }


def build_stroop_trials(count: int = 5) -> list[dict[str, Any]]:
    """Trial: spoken color vs digit on matrix (congruent or incongruent)."""
    colors = list(STROOP_DIGIT_COLOR.values())
    trials: list[dict[str, Any]] = []
    for _ in range(count):
        digit = random.randint(1, 3)
        digit_color = STROOP_DIGIT_COLOR[digit]
        congruent = random.random() < 0.4
        spoken = digit_color if congruent else random.choice([c for c in colors if c != digit_color])
        trials.append(
            {
                "digit": digit,
                "spoken": spoken,
                "answer": digit_color,
                "congruent": congruent,
            }
        )
    return trials


def validate_story_order(transcript: str, events: list[str]) -> dict[str, Any]:
    """
    Verifica daca copilul a dat ordinea corecta.
    Accepta: propozitiile in ordine, sau 'first second third' + keywords.
    """
    bl = (transcript or "").lower()
    # Potrivire secventiala: fiecare eveniment apare dupa precedentul
    positions: list[int] = []
    for ev in events:
        key = ev.lower().split(".")[0].strip()[:20]
        # keyword scurt din propozitie
        kw = key.split()[-2:] if len(key.split()) >= 2 else [key.split()[0] if key.split() else key]
        found = -1
        for fragment in (" ".join(kw), kw[-1] if kw else ""):
            if fragment and fragment in bl:
                found = bl.find(fragment)
                break
        if found < 0:
            positions.append(-1)
        else:
            positions.append(found)
    ordered = all(positions[i] >= 0 and positions[i] < positions[i + 1] for i in range(len(positions) - 1))
    # Ordine explicita first/second/third
    ord_words = ["first", "second", "third", "one", "two", "three"]
    explicit = sum(1 for w in ord_words if w in bl) >= 2
    correct = ordered or (explicit and all(p >= 0 for p in positions))
    return {"correct": correct, "positions": positions, "events": events}


# 2.1 Build the Model — nivele progresive (pattern Hub + descriere pentru Gemini Vision)
BUILD_MODEL_LEVELS: list[dict[str, Any]] = [
    {
        "level": 1,
        "action": "build_model_1",
        "name": "tower",
        "description": "a small vertical tower of 2 or 3 stacked LEGO bricks in the center",
    },
    {
        "level": 2,
        "action": "build_model_2",
        "name": "line",
        "description": "a horizontal row of 3 LEGO bricks placed side by side",
    },
    {
        "level": 3,
        "action": "build_model_3",
        "name": "l_shape",
        "description": (
            "an L-shape made of 3 LEGO bricks: two stacked vertically "
            "plus one extending to the right at the bottom"
        ),
    },
]


def build_model_level(level: int) -> dict[str, Any]:
    """Returneaza definitia nivelului (1-based); ultimul nivel daca depaseste lista."""
    idx = max(0, min(int(level) - 1, len(BUILD_MODEL_LEVELS) - 1))
    return BUILD_MODEL_LEVELS[idx]


def build_model_verify_prompt(description: str) -> str:
    """Prompt Gemini Vision pentru verificarea constructiei LEGO vs modelul afisat."""
    desc = (description or "a LEGO build").strip()
    return f"""You verify a child's LEGO build against a target pattern shown on a robot display.
Target pattern: {desc}
Output ONLY valid JSON with these fields:
- "id": integer (0=unclear/empty, 2=LEGO build clearly visible)
- "match": boolean (true if the build clearly matches the target pattern)
- "match_score": number from 0.0 to 1.0
No markdown, no explanation.
Example: {{"id":2,"match":true,"match_score":0.85}}
"""
