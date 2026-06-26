# TriSense - setup pe un PC nou

Acest branch (`pcnou`) este pregatit ca proiectul sa poata fi clonat pe alt calculator fara sa depinda de fisierele locale de pe PC-ul initial.

## Ce contine repository-ul

- codul robotului si al aplicatiei PC (`main.py`, `main_robot.py`, `trisense/`, `run_voice_dialog.py`);
- sursele lucrarii si prezentarii in `licenta/`;
- imaginile folosite in lucrare/prezentare in `licenta/images/`;
- prezentarile model in `prezentari/`;
- exemple de configurare: `.env.example` si `secrets.example.py`.

## Ce NU este comitat intentionat

- `.env` - configuratia locala a PC-ului;
- `secrets.py` - configuratia ESP32;
- `cheie_google.json` sau alte chei/API keys;
- filmari brute, arhive si fisiere temporare generate la compilarea LaTeX.

## Pasi pe PC nou

1. Cloneaza repository-ul si intra pe branch:

```powershell
git clone https://github.com/DoublxB/Trisense.git
cd Trisense
git switch pcnou
```

2. Creeaza fisierele locale de configurare:

```powershell
copy .env.example .env
copy secrets.example.py secrets.py
```

3. Completeaza local, fara commit:

- in `.env`: IP-ul PC-ului, IP-urile robotului/camerei, cheia/API config pentru Gemini/Vertex;
- in `secrets.py`: SSID, parola Wi-Fi, IP-ul PC-ului si brokerul MQTT.

4. Instaleaza dependintele Python folosite de proiect (in functie de mediul local):

```powershell
py -m pip install -r requirements.txt
```

Daca nu exista `requirements.txt` in checkout-ul folosit, instaleaza manual pachetele cerute de erorile de import (ex. `python-dotenv`, `paho-mqtt`, `google-genai`, `edge-tts`, bibliotecile Google Cloud TTS daca folosesti Cloud TTS).

## Rulare uzuala

Pe PC:

```powershell
py run_voice_dialog.py
```

Pentru verificarea constructiilor LEGO cu ESP32-CAM, porneste si puntea de viziune:

```powershell
py testare/vision_esp32cam_bridge.py
```

Pe ESP32 se incarca `secrets.py` si firmware-ul `main_robot.py` (ca `main.py` pe placa), de exemplu:

```powershell
py -m mpremote connect COM7 cp secrets.py :secrets.py
py -m mpremote connect COM7 cp main_robot.py :main.py
py -m mpremote connect COM7 reset
```

Portul COM poate fi diferit pe PC-ul nou.

## Prezentare si licenta

Prezentarea principala este:

- `licenta/prezentare-5min.tex`
- `licenta/prezentare-5min.pdf`

Compilare:

```powershell
cd licenta
pdflatex -interaction=nonstopmode prezentare-5min.tex
pdflatex -interaction=nonstopmode prezentare-5min.tex
```

Lucrarea compacta este:

- `licenta/main-compact.tex`

Pentru lucrare este recomandat XeLaTeX, conform comentariilor din fisier.

## Status prezentare

Prezentarea are 11 slide-uri:

1. Titlu
2. De ce aceasta tema
3. Structura lucrarii scrise
4. Problema si scopul
5. Cum e construit sistemul
6. Cum circula vocea
7. Cablajul electric
8. Functionalitati terapeutice
9. Cele 5 emotii
10. Concluzii si directii viitoare
11. Q&A / demo live

Slide-ul cu cele 5 emotii accepta automat poze optionale in `licenta/images/`:

- `emotie-happy.jpg`
- `emotie-sad.jpg`
- `emotie-surprised.jpg`
- `emotie-angry.jpg`

`robot-meltdown-frontal.png` exista deja si este folosit pentru meltdown.

## Note pentru urmatorul agent Cursor

- Nu comita `.env`, `secrets.py`, chei Google sau parole Wi-Fi.
- Daca robotul nu se conecteaza, verifica mai intai IP-ul PC-ului in reteaua curenta si actualizeaza `.env` + `secrets.py`.
- Daca vocea merge pe PC dar nu pe robot, verifica firewall-ul Windows pentru porturile TCP audio si MQTT.
- Pentru demo, cele mai stabile functionalitati sunt: dialog vocal, Ghiceste emotia, Urmeaza tiparul, Build the Model, poveste co-construita, respiratie ghidata, dans si raport/metrici.
- Estimarea timpului este implementata, dar masurarea prin voce poate include latenta STT; pentru precizie e recomandata varianta cu buton.
