# LMS-ESP32 v2.0 — referinta pentru TriSense (Anton’s Mindstorms)

Acest fisier rezuma informatii oficiale utile pentru placa **LMS-ESP32 v2.0** folosita la robot.  
Sursa principala: [documentatie placi expansiune](https://www.antonsmindstorms.com/doc-category/expansion-board-documentation/).

## Link-uri directe (Anton)

| Resursa | URL |
|--------|-----|
| Pinout LMS-ESP32 v2 | <https://www.antonsmindstorms.com/docs/lms-esp32-v2-pinout/> |
| Getting started LMS-ESP32 v2 | <https://www.antonsmindstorms.com/docs/getting-started-with-your-new-lms-esp32v2-board/> |
| Firmware selector / flasher | <https://firmware.antonsmindstorms.com/> |
| Serie tutoriale (SPIKE / Robot Inventor) | articole din site-ul Anton (partea 0–4) |

## Ce este placa (rezumat)

- MCU: **ESP32-PICO-V3-02**, **8 MB flash**, **2 MB PSRAM** (conform paginii de pinout).
- Destinatie: hub-uri LEGO inteligente (SPIKE Prime, Robot Inventor, Technic Hub) + **UART catre hub** pentru protocoale tip LPF2 / PUPRemote.
- Pini expusi la **3.3 V** — nu conecta 5 V direct pe GPIO; curenti mari pot deteriora placa.

## Pini relevanti pentru TriSense (din documentatia de pinout)

- **UART catre hub:** **GPIO 7** si **GPIO 8** (in documentatie: SPI_DATA0 / SPI_DATA1, rol **UART to hub**).  
  Firmware-ul Anton (`lms_esp32`, `pupremote` built-in) foloseste de obicei **TX/RX** pentru legatura cu portul LEGO — **nu schimba** la intamplare daca merge handshake-ul.
- **I2C implicit (default):** **GPIO 4 (SCK)** / **GPIO 5 (SDA)** in tabel; in multe exemple se foloseste si **GPIO 21 (SDA)** / **GPIO 22 (SCL)** pentru senzori I2C (ex. HuskyLens) — verifica firele tale si exemplul din proiect (`main_robot.py`).
- **NeoPixel onboard:** GPIO **25**.
- **USB serial:** UART0 pe **GPIO 1 (TX)** / **GPIO 3 (RX)** — mesaje de boot; evita sa folosesti 1/3 pentru altceva daca vrei serial curat.

## Wi-Fi si ADC (atenție la masuratori)

Conform notei din documentatie: **ADC2** poate fi **mai putin fiabil cand Wi-Fi este activ**; ADC1 e de preferat pentru citiri analogice stabile cu Wi-Fi pornit. Pentru TriSense, daca nu folosesti ADC, impactul e limitat.

## Pini de strapping

Pini marcati cu atentionare in documentatie (ex. 0, 2, 12, 15) pot influenta **modul de boot**. Daca ai comportamente ciudate la reset sau la programare, verifica schema si documentatia Anton despre **strapping pins**.

## Firmware

- Optiuni mentionate pe site: **Bluepad**, **MicroBlocks**, **MicroPython**.
- Proiectul TriSense foloseste **MicroPython** + biblioteci Anton (ex. **PUPRemote** / LPF2 integrate in firmware).
- Actualizare firmware: **Chrome / Edge** + [firmware.antonsmindstorms.com](https://firmware.antonsmindstorms.com/).

## PUPRemote / LPF2 — heartbeat (Anton, doc oficial)

- In bucla **sincrona**, `p.process()` trebuie apelat **preferabil cel putin o data la ~20 ms** (vezi API in documentatia PUPRemote).
- Varianta **`process_async()`** + `asyncio` ruleaza heartbeat-ul la **minim ~15 Hz** (interval recomandat **≤ 66 ms**) **in paralel** cu bucla principala — util cand **I2C (HuskyLens)** sau alte operatii **blocheaza** mult timp; altfel in `lpf2.py` dupa **~1000 ms** fara activitate apare *„line is dead”* si se reinitializeaza legatura.

## Legatura cu codul din acest repo

- `main_robot.py` — Wi-Fi, MQTT, **PUPRemoteSensor** (handshake Hub), HuskyLens pe **SoftI2C**; bucla foloseste **`asyncio` + `process_async`** ca in exemplele LMS-ESP32 din doc-ul Anton.
- Nu suprascrie pe ESP fisierele `lpf2.py` / `pupremote.py` din firmware daca variantele built-in functioneaza (recomandare din sesiunile anterioare de debug).

## Discord / comunitate

Site-ul Anton indica server **Discord** pentru intrebari suplimentare (link pe pagina *Getting started*).

---
*Continut tehnic aliniat public cu paginile Anton’s Mindstorms (LMS-ESP32 v2 pinout + getting started). Pentru detalii complete, vezi URL-urile de mai sus.*
