# Moduri funcționare ESP32

## Mod producție (robot pornește automat)
- NU uploda fișierul `repl` pe device.
- La alimentare, `main.py` rulează → robotul pornește direct.
- Fără reset, fără PC.

## Mod programare (REPL liber)
- Uploadează fișierul gol `repl`: `py -m mpremote connect COM6 cp repl :repl`
- La următorul boot, `main.py` vede `repl` și iese imediat → REPL liber.
- Pentru a reveni la mod producție: șterge `repl` de pe device.

---

# Recovery: "could not enter raw repl"

Când `main.py` rulează la boot, ocupă serialul și mpremote nu poate intra în raw REPL.

## Procedură de recuperare

### Pasul 1: Pregătire
- **Deconectează cablul LEGO** de la LMS-ESP32 (hub-ul nu trebuie legat în timpul upload-ului)
- Verifică că **doar ESP32** e conectat la PC (nu și hub-ul pe același USB)
- Asigură-te că portul COM6 e cel corect (Device Manager → Porturi COM)

### Pasul 2: Reset + connect rapid
1. Ține apăsat butonul **RESET** pe ESP32
2. Rulează: `py -m mpremote connect COM6`
3. **Eliberează RESET** imediat – ESP32 pornește
4. Dacă apare `>>>` sau orice text, apasă **Ctrl+C** de 2–3 ori (oprește main.py)

### Pasul 3: Șterge/redenumire main.py
Dacă ai ajuns la REPL (`>>>`):
```python
import os
if 'main.py' in os.listdir():
    os.rename('main.py', 'main_robot.py')
    print('OK - main.py redenumit')
```
Apoi **Ctrl+D** (soft reset).

### Pasul 4: Upload fișiere
După ce main.py nu mai rulează la boot:
```powershell
py -m mpremote connect COM6 cp boot.py :boot.py
py -m mpremote connect COM6 cp main_robot.py :main_robot.py
py -m mpremote connect COM6 cp lpf2.py :lpf2.py
py -m mpremote connect COM6 cp pupremote.py :pupremote.py
py -m mpremote connect COM6 cp pyhuskylens.py :pyhuskylens.py
```

Dacă ai încărcat doar `pupremote.py` din repo și apare **`AttributeError: 'LPF2' object has no attribute 'update_payload'`**, încarcă neapărat și **`lpf2.py`** din același proiect (cele două trebuie să fie din aceeași versiune).

### Pasul 5: Rulare (înlocuiesti COM6 cu portul ESP, ex. COM7)

```powershell
python -m mpremote connect COM7 run main_robot.py
```

---

## Dacă nu merge (COM6 = hub LEGO?)

Dacă COM6 e **hub-ul SPIKE Prime**, nu e ESP32. Conectează **doar** LMS-ESP32 la PC și verifică ce port COM nou apare.
