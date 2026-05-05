# TriSense — Ghid pentru Marius și coechipieri / coach

Pași numerotați ca robotul să meargă și să poți testa cu **microfon de pe laptop**, apoi să spui **„dance”** (brațe LEGO).

Presupun că proiectul este clonat pe PC și ai rulat `pip install -r requirements.txt`.

### Pornire automată pe ESP (după `main_robot.py` → `main.py`)

MicroPython pornește singur la alimentare **`boot.py`**, apoi **`main.py`** de pe flash-ul ESP. În repo, programul robotului este **`main_robot.py`**; pe placă trebuie copiat **sub numele `main.py`** ca să ruleze fără să dai Run manual.

**Varianta A — `mpremote` (recomandat)**

În **PowerShell / CMD**, din folderul proiectului (înlocuiești `COM7` cu portul ESP din Manager dispozitive):

```powershell
cd C:\Users\impact\Desktop\Licenta mea
python -m mpremote connect COM7 cp main_robot.py :main.py
python -m mpremote connect COM7 reset
```

Opțional, verifici ce e pe flash:

```powershell
python -m mpremote connect COM7 ls
```

**Rulare firmware din sursa locala (fără depindere de `main.py` pe flash):**

```powershell
python -m mpremote connect COM7 run main_robot.py
```

Comanda aceasta citește **`main_robot.py` din folderul curent pe PC** și îl execute pe placă — utilă pentru teste rapide sau când **`main.py` de pe flash** nu e sincron cu repo-ul.

Pentru **pornire la alimentare fără PC**, **`main.py` trebuie să existe și să fie mare** pe flash-ul ESP (copiat cu `cp main_robot.py :main.py` mai sus).

**Important:** fișierul **`main.py`** din rădăcina repo-ului este programul **Pybricks pentru hub LEGO** — **nu** se copiază pe ESP. Pe ESP **`main.py`** = conținutul lui **`main_robot.py`**.

---

### Pasul 1 — Pornești Mosquitto (broker MQTT) pe calculator

MQTT trebuie să ruleze pe același PC al cărui **IPv4** îl folosești la `MQTT_BROKER`.

Într-un terminal (**CMD sau PowerShell**):

```powershell
mosquitto -v
```

sau, dacă nu e în PATH:

```powershell
& "C:\Program Files\mosquitto\mosquitto.exe" -v
```

Lasă această fereastră deschisă. Fără broker, ESP-ul și creierul de pe laptop nu comunică peste MQTT.

---

### Pasul 2 — Schimbi credențiale Wi‑Fi și IP-uri în proiect

În sala ta rețeaua poate fi alta decât în laborator — trebuie aliniată **aceeași rețea** pentru laptop și robot.

**a) În `main_robot.py` (firmware ESP32)**

- `WIFI_SSID` — numele rețelei Wi‑Fi (ex. `Orange-292q-2.4G`).
- `WIFI_PASS` — parola acelei rețele.
- `MQTT_BROKER` — **IPv4-ul laptopului** unde rulează Mosquitto (vezi Pasul 3 după ce îl afli cu `ipconfig`).

După modificări pui din nou firmware-ul pe ESP (`mpremote`, Thonny etc.), cum faceți în echipă.

**b) În `.env`** (în rădăcina proiectului pe laptop — fișierul nu e în Git, îl creezi tu sau îl copiezi cu valorile tale)

- `MQTT_BROKER` — același IP ca la Mosquitto (laptopul).
- `PC_VOICE_IP` — **IP-ul robotului ESP32** după ce se conectează la Wi‑Fi (vezi Pasul 4). E folosit pentru TTS/audio TCP către difuzor când rulezi scriptul de la Pasul 6.

---

### Pasul 3 — Îți afli IPv4-ul pe laptop (`ipconfig`)

Într-un terminal nou:

```powershell
ipconfig
```

Caută secțiunea **Wireless LAN adapter Wi‑Fi** (sau echivalent activ) și notează:

**IPv4 Address** → acesta este IP-ul pe care îl pui la `MQTT_BROKER` în `main_robot.py` și în `.env`.

*(Ex.: `192.168.100.134` — la voi poate fi alt număr.)*

---

### Pasul 4 — Cum îl vezi pe IP-ul robotului

IP-ul robotului (**ESP32**) **nu este** cel al laptopului — îl vezi în consolă **când se pornește** și după Wi‑Fi.

1. Conectezi ESP-ul la laptop prin **USB**.

2. Deschizi **consola serială** ca să urmărești tot ce printează ESP-ul (Wi‑Fi, MQTT, hub LEGO, mesaje MQTT, erori). În **PowerShell** sau **CMD**, din folderul proiectului rulezi:

```powershell
cd C:\Users\impact\Desktop\Licenta mea
python -m mpremote connect COM7
```

La calculatorul tău portul poate fi **`COM6`**, **`COM8`** etc. Verifică în Windows → **Manager dispozitive** → **Porturi (COM și LPT)** ce număr are ESP-ul USB. Înlocuiești `COM7` cu portul corect.

**Ieși** din sesiunea mpremote cu **`Ctrl + ]`** (dacă nu merge, încearcă **`Ctrl + x`**).

Poți lasa această fereastră deschisă **în paralel** cu Mosquitto și cu `test_laptop_mic.py`, ca să vezi live în consolă handshake-ul, mesajele și ce se întâmplă când vorbești la microfon.

Alternativă: **Thonny**, interpretor MicroPython pentru ESP și același port COM.

3. În output apare o linie de forma:

```text
>>> WiFi CONECTAT! IP: 192.168.xxx.yyy
```

Acest **`192.168.xxx.yyy`** este IP-ul robotului → îl pui în **`.env` la `PC_VOICE_IP`** pentru testele cu microfonul de laptop. Dacă routerul ia alt IP după reboot, actualizezi din nou.

---

### Pasul 5 — După handshake: Wi‑Fi fără cablu și buton hub

Flux recomandat la prezentare:

1. Cu **cablu USB** legat între laptop și LMS-ESP32, urmărești în consolă că **LPF2** face handshake cu hub-ul („conectat la hub”, mesaje stabile).

2. Când handshake-ul pare **OK**, **deconectezi cablul USB de la laptop** ca robotul să nu mai depindă firul spre PC. Alimentarea rămâne cum aveți voi pozat (ex. hub / baterie).

3. **Apeși butonul hub-ului** LEGO (SPIKE Prime) ca să pornească programul Pybricks care comunică cu ESP-ul prin LPF2.

În sala de curs Mosquitto pe laptop **rămâne deschis** pe rețea; robotul comunică peste Wi‑Fi.

---

### Pasul 6 — Al doilea terminal: `test_laptop_mic.py`

Deschizi **încă un terminal** (Mosquitto poate să ruleze mereu în primul).

În folderul proiectului:

```powershell
cd C:\Users\impact\Desktop\Licenta mea
```

*(sau unde ai clonat TriSense)*

Apoi:

```powershell
py testare\test_laptop_mic.py
```

sau:

```powershell
python testare\test_laptop_mic.py
```

Accepți permisiunea de **microfon** dacă Windows o cere.

---

### Pasul 7 — Vorbești: „dance”

Când scriptul cere să vorbești la microfon:

- spui clar, în engleză: **`dance`**.

Atunci TriSense procesează vocea și poate trimite comanda către robot (MQTT / logică defină în cod: mișcare brațe dacă hub-ul și programul Pybricks sunt setate pentru asta).

---

## Checklist rapid (pentru coach)

| Nr. | Acțiune |
|-----|---------|
| **1** | Mosquitto pornit (`mosquitto -v`) |
| **2** | Schimbă în `main_robot.py`: Wi‑Fi + `MQTT_BROKER` = IPv4 laptop; în `.env`: același broker + la nevoie alte variabile pentru PC |
| **2b** | `
e cp main_robot.py :main.py` apoi `reset` (ESP pornește singur — vezi secțiunea „Pornire automată”) |
| **3** | `ipconfig` → notezi **IPv4** laptop pentru broker |
| **4** | `python -m mpremote connect COM7` (sau alt COM) → notezi **IP robot** pentru `PC_VOICE_IP` în `.env` |
| **5** | Handshake vizibil → scoți USB de la laptop → apeși **butonul hub** |
| **6** | Terminal separat → `python testare\test_laptop_mic.py` |
| **`7`** | Vorbești la microfon **`dance`** |

---

## Notă despre `secrets.py` pe ESP

În alt loc cu **Wi‑Fi diferit**:

- Obligatoriu actualizezi **`secrets.py`** (Wi‑Fi, `MQTT_BROKER`, `PC_VOICE_IP`), copiat pe ESP și **`.env`** pe laptop.

- **Copiere `secrets.py` pe placă** (din folderul proiectului, înlocuiesti `COM7`):

```powershell
python -m mpremote connect COM7 cp secrets.py :secrets.py
```

- **`secrets.py` pe placă**: conține `GEMINI_API_KEY`, `WIFI_*`, și `PC_VOICE_IP` pentru fluxuri unde ESP trimite voce către PC fără IP în MQTT.

Nu comita `secrets.py` sau `.env` în Git dacă echipe cu chei diferite lucrează separat — folosiți exemple din repo (`secrets.example.py`, `.env.example` dacă există).

---

## Dacă ceva nu merge

- Firewall / Mosquitto doar în mod „local only” poate împiedica conectarea ESP de pe aceeași rețea Wi‑Fi → verificați că ascultă pe IP-ul bun (ex. port 1883).
- `PC_VOICE_IP` greșit în `.env` → TTS/audio TCP către ESP poate eșua; MQTT poate merge în paralel pentru alte comenzi.
- Comenzi MQTT manuale: payload JSON valid, ex.: `{"action":"dance"}`. În PowerShell adesea ajută: `$body='{"action":"dance"}'` apoi `-m $body`.

---

*Document pentru colegi și coach-uri TriSense.*
