# TriSense — Funcționalități posibile: testare psihologică & valoare terapeutică

**Document:** `docs/new_poss_features.md`  
**Proiect:** TriSense — robot companion pentru copii neurodivergenți (Lego-Based Therapy, WRO 2025)  
**Scop:** catalog de procedee inspirate din evaluări cognitive și exerciții terapeutice, adaptabile la hardware-ul actual (Hub LEGO, LMS-ESP32, HuskyLens / ESP32-CAM, voce Gemini, MQTT).

> **Notă importantă (etică & licență)**  
> TriSense **nu înlocuiește** un psiholog clinician și **nu oferă diagnostic** (ASD, ADHD etc.).  
> Funcțiile de mai jos sunt **instrumente de suport** în sesiuni ghidate: joc structurat, observare comportamentală, metrici pentru terapeut.  
> Formulare recomandată: *„exercițiu terapeutic inspirat din procedee standard, nu test clinic validat”*.

---

## 1. Ce există deja în proiect

| Funcție | Stare | Construct psihologic |
|---------|--------|----------------------|
| Salut + recunoaștere față | parțial (`vision/tags`, ID 1) | relație terapeutică, reducere anxietate inițială |
| Breathing Buddy | implementat (`breathing_show`, cmd 12) | reglare emoțională, calm, atenție corporală |
| Clasificare obiecte LEGO | parțial (`vision/tags`, ID 2+) | atenție selectivă, categorizare |
| Guess the Emotion (Act. 6) | implementat | recunoaștere emoții, vocabular afectiv |
| Follow the Pattern (Act. 7) | implementat | memorie secvențială, imitare |
| Dans / comenzi motorii | implementat | coordonare, imitare, engagement |
| Demo juriu | implementat (`judges_demo`) | prezentare, engagement social |
| Metrici sesiune | parțial (`trisense_metrics.csv`, `MetricsLogger`) | timp reacție, stare, ID văzut |

---

## 2. Funcționalități din raportul WRO (PDF) — de completat

### 2.1 Build the Model (Observational Learning — inspirat Turnul din Hanoi)

**Procedeu psihologic inspirat:** Tower of Hanoi / teste de planificare vizuo-spatială (funcții executive).

**Descriere procedeu în TriSense:**

1. Robot salută copilul (față — HuskyLens sau ESP32-CAM).
2. Afișează pe **matricea Hub** un model țintă (pattern LED).
3. Copilul are **30 s** să reproducă structura din cărămizi LEGO.
4. Camera verifică potrivirea (HuskyLens ID antrenat **sau** ESP32-CAM + Gemini).
5. Feedback: succes → high-five + model mai complex; eșec → încurajare + repetare.

**Valoare terapeutică:**

- antrenarea **memoriei de lucru** și a **atenției la detaliu**;
- **persistență** la task (încercări repetate fără pedeapsă);
- transfer spre LBT: urmărirea unui model, planificare pas-cu-pas;
- date pentru terapeut: timp până la reușită, număr încercări, nivel dificultate.

**Feasibility:** ★★★★☆ (ESP32-CAM + state machine + matrix Hub)

**Metrici sugerate:** `model_level`, `attempts`, `success`, `build_duration_s`, `match_score`

---

### 2.2 Memory Numbers + culori LEGO

**Procedeu inspirat:** span de memorie vizuală / Corsi block-tapping (secvențe).

> **Notă hardware:** matricea 5×5 a Hub-ului LEGO SPIKE Prime afișează **cifre și pattern-uri** (luminozitate 0–100%), nu culori RGB. Nu se adaugă extensii senzor suplimentare. Culorile sunt **reprezentate prin cifre** (convenție stabilită cu copilul înainte de joc, ex. `1 = red`, `2 = green`, `3 = blue`).

**Procedeu:**

1. Înainte de joc: robot anunță convenția vocal: *„1 is red, 2 is green, 3 is blue."*
2. Robot afișează o secvență de cifre pe matrice, câte una la un moment (ex. **1** → **2** → **1**).
3. Copilul arată cărămida LEGO de culoarea corespunzătoare cifrei, pe rând, camerei (ESP32-CAM verifică culoarea).
4. Secvența se prelungește progresiv (2 → 3 → 4 elemente).

**Valoare terapeutică:**

- **memorie de lucru** și **secvențiere**;
- legătura simbol abstract (cifră) → culoare → obiect concret (LEGO) — antrenament cognitiv util la ADHD;
- toleranță la eroare cu feedback blând.

**Feasibility:** ★★★★☆

**Metrici:** `sequence_length`, `correct_steps`, `max_span_reached`

---

### 2.3 Dance with me (din PDF — extindere)

**Procedeu inspirat:** imitare motorie, terapie prin mișcare.

**Procedeu:** robot dansează (brațe, cap, roți); copilul imită; opțional CAM detectează prezență copil în cadru.

**Valoare terapeutică:**

- **coordonare motorie** și **imitare socială** (deficit frecvent la ASD);
- engagement pozitiv, legătură corp–emoție;
- reducere sedentarism în sesiune.

**Feasibility:** ★★★★★ (deja parțial via `dance`)

**Metrici:** `dance_duration_s`, `engagement_detected`

---

## 3. Funcționalități noi — legate de procedee psihologice

### 3.1 Stop & Go (Go / No-Go simplificat)

**Procedeu inspirat:** teste de **inhibiție a răspunsului** (Go/No-Go, folosite în research ADHD).

**Procedeu:**

> **Notă hardware:** Matricea 5x5 a Hub-ului afișează **cifre și pattern-uri** (luminozitate 0–100%), nu culori RGB. Nu se adaugă extensii senzor. Culorile sunt **reprezentate prin cifre** anunțate vocal înainte de joc: `1 = Go`, `0 = Freeze`. Lumina centrală a Hub-ului (`hub.light`) oferă indiciu vizual suplimentar — singura sursă de culoare reală pe Hub.

- Înainte de joc: robot anunță vocal: *„When you see 1 — dance! When you see 0 — freeze!”*
- Matrice afișează **1** (Go) → copilul spune „dance” / robot dansează; lumina centrală verde.
- Matrice afișează **0** (Stop) → copilul rămâne nemișcat; lumina centrală roșie.
- Alternanță aleatoare, ritm lent (adaptat vârstă ~6–12 ani).

**Valoare terapeutică:**

- **control inhibitor** și **atenție susținută**;
- reducerea impulsivității în context sigur, ludic;
- progres măsurabil (rata erori „dance pe 0”).

**Feasibility:** ★★★★★

**Metrici:** `trial_type`, `correct_inhibition`, `false_go_count`, `reaction_ms`

---

### 3.2 Turn-taking cooperativ (rândul meu / rândul tău)

**Procedeu inspirat:** antrenament **interacțiune socială** din Lego-Based Therapy (Daniel LeGoff).

**Procedeu:**

- Robot: „My turn” → o mișcare; „Your turn” → copilul imită sau răspunde vocal.
- Extinde Follow the Pattern cu **roluri sociale explicite**.

**Valoare terapeutică:**

- **rândul la cuvânt**, așteptare, cooperare;
- competențe sociale pentru ASD;
- predictibilitate (script clar reduce anxietate).

**Feasibility:** ★★★★★

**Metrici:** `turn_index`, `child_response_ok`, `latency_ms`

---

### 3.3 Check-in emoțional (scala simplă 1–3)

**Procedeu inspirat:** eșarfe emoționale / mood scales din terapie (nu diagnostic).

**Procedeu:**

- Robot întreabă: „How do you feel? Happy, okay, or sad?”
- Opțional: copilul spune vocal numărul emoției (1/2/3) sau arată cărămida LEGO de culoarea asociată camerei (ESP32-CAM detectează culoarea).
- Robot răspunde empatic + propune activitate (respirație dacă „sad/okay”).

**Valoare terapeutică:**

- **conștientizare emoțională**;
- jurnal mood per sesiune pentru terapeut;
- legătură cu Breathing Buddy ca intervenție de reglare.

**Feasibility:** ★★★★★

**Metrici:** `mood_label`, `timestamp`, `follow_up_activity`

---

### 3.4 Rutine sociale scriptate (Social Stories lite)

**Procedeu inspirat:** Social Stories (Carol Gray), scripturi LBT.

**Procedeu:**

- Secvență fixă TTS: salut → întrebare deschisă → pauză → compliment → la revedere.
- Aceleași formulări la fiecare sesiune (predictibilitate).

**Valoare terapeutică:**

- reduce **anxietatea socială** prin structură;
- expunere gradată la interacțiune;
- antrenează **formule de politețe** fără presiune.

**Feasibility:** ★★★★★

**Metrici:** `script_step`, `session_completed`

---

### 3.5 Imită emoția (extindere Act. 6)

**Procedeu inspirat:** task-uri de **recunoaștere și exprimare emoțională** (terapie ASD).

**Procedeu:**

1. Robot arată emoția (matrice + gest Hub).
2. Copilul imită fața/gestul.
3. Verificare: terapeut manual **sau** ESP32-CAM + prompt Gemini.

**Valoare terapeutică:**

- **exprimare** emoții, nu doar recunoaștere;
- oglindire terapeutică (mirroring);
- legătură corp–emoție.

**Feasibility:** ★★★☆☆ (evaluare automată mai grea)

**Metrici:** `emotion_shown`, `imitation_detected`, `attempts`

---

### 3.6 Joint Attention (atenție comună)

**Procedeu inspirat:** paradigme JA din research ASD (privire + obiect comun).

**Procedeu:**

1. Robot orientează **capul** spre zonă + voce: „Look at the red block!”
2. Copilul plasează / arată piesa în cadru CAM.
3. Succes → recompensă socială (high-five, cmd braț).

**Valoare terapeutică:**

- **atenție comună** — deficit frecvent la ASD;
- legătură indicație socială (robot) ↔ obiect real;
- fundament comunicare și LBT în grup.

**Feasibility:** ★★★☆☆

**Metrici:** `cue_type`, `object_in_frame`, `time_to_joint_attention_s`

---

### 3.7 Pauză de reglare / prevenție overload

**Procedeu inspirat:** **sensory breaks** și interocepție (terapie ocupațională).

**Procedeu:**

- După N minute de joc sau eșec repetat → robot propune automat 2 cicluri respirație.
- Matrice calmă, voce lentă, fără mișcări bruște roți.

**Valoare terapeutică:**

- previne **suprasolicitare senzorială** (meltdown);
- învață copilul să accepte pauze;
- leagă activitate cognitivă de **autorreglare**.

**Feasibility:** ★★★★★

**Metrici:** `trigger_reason`, `break_duration_s`, `resumed_calm`

---

### 3.8 Flexibilitate cognitivă (reguli care se schimbă — mini-WCST)

**Procedeu inspirat:** Wisconsin Card Sorting (concept: schimbare regulă), **versiune simplificată**.

**Procedeu:**

- Runda 1: „Show me something **red**” (CAM).
- Runda 2: acum contează **forma** (cub vs cilindru).
- Robot explică blând schimbarea regulii.

**Valoare terapeutică:**

- **flexibilitate cognitivă** (rigiditate frecventă la ASD);
- toleranță la schimbare de reguli în mediu controlat;
- *Nu* pretinde validare WCST — doar inspirație.

**Feasibility:** ★★★☆☆ (prompt CAM robust)

**Metrici:** `rule_phase`, `perseveration_errors`, `switch_success`

---

### 3.9 Delayed gratification (așteptare recompensă)

**Procedeu inspirat:** paradigme **delay of gratification** (autocontrol).

**Procedeu:**

- „If you wait 10 seconds without moving, we dance together!”
- Countdown vizual pe matrice Hub.

**Valoare terapeutică:**

- **autocontrol** și așteptare;
- transfer spre comportament zilnic (rând, răbdare).

**Feasibility:** ★★★★☆

**Metrici:** `wait_duration_s`, `success`, `premature_response`

---

### 3.10 Raport sesiune pentru terapeut

**Procedeu inspirat:** **monitoring comportamental** în terapie (psihologi, LBT).

**Procedeu:**

- Extindere `MetricsLogger` (`trisense/metrics_logger.py`): evenimente per joc în CSV/JSONL.
- La final sesiune: sumar (timp reacție mediu, rata succes emoții, număr pauze).

**Valoare terapeutică:**

- obiectivitate în **progres pe sesiuni**;
- argument solid pentru licență (date + etică);
- terapeutul ajustează dificultatea — robotul nu „diagnostichează”.

**Feasibility:** ★★★★★ (infrastructură parțial existentă)

**Metrici:** agregate per `session_id`, `child_name`, `activity`

---

### 3.11 N-Back verbal simplificat (1-back / 2-back)

**Procedeu inspirat:** sarcini **N-back** pentru memorie de lucru (versiune pediatrică, simplificată).

**Procedeu:**

- Robot spune o secvență de cuvinte scurte (ex. „ball, car, ball...”).
- Copilul spune „yes” când cuvântul curent este același cu cel de acum 1 pas (1-back), apoi 2-back la nivel avansat.
- Răspunsul este validat vocal (STT).

**Valoare terapeutică:**

- antrenează **actualizarea memoriei de lucru**;
- dezvoltă atenția auditivă și controlul răspunsului;
- progresie clară pe dificultate (1-back -> 2-back).

**Feasibility:** ★★★☆☆

**Metrici:** `n_level`, `hit_rate`, `false_alarm_rate`, `reaction_ms`

---

### 3.12 Categorie rapidă (semantic fluency mini)

**Procedeu inspirat:** probe de **fluenta semantică** (versiune de joc, non-clinică).

**Procedeu:**

- Robot dă o categorie: „animals”, „colors”, „fruits”.
- Copilul spune cât mai multe exemple în 20-30 s.
- Sistemul numără răspunsuri valide și repetările.

**Valoare terapeutică:**

- stimulează **acces lexical** și flexibilitate verbală;
- susține inițierea verbală și încrederea în comunicare;
- util pentru monitorizarea progresului verbal în timp.

**Feasibility:** ★★★☆☆

**Metrici:** `category`, `valid_count`, `repetition_count`, `time_window_s`

---

### 3.13 Ascultă și execută (2-step -> 3-step commands)

**Procedeu inspirat:** task-uri de **following instructions** și secvențiere auditivă.

**Procedeu:**

- Robot dă instrucțiuni în 2 pași: „Touch red brick, then clap.”
- Ulterior trece la 3 pași.
- Copilul confirmă vocal sau prin acțiune observată de terapeut.

**Valoare terapeutică:**

- crește **înțelegerea auditivă secvențială**;
- îmbunătățește organizarea comportamentală;
- util pentru transfer în activități școlare.

**Feasibility:** ★★★★☆

**Metrici:** `step_count`, `completed_steps`, `prompt_repeats`

---

### 3.14 Stroop color-word adaptat (versiune copii)

**Procedeu inspirat:** **Stroop** (inhibiție + atenție selectivă), adaptat ludic.

**Procedeu:**

> **Notă hardware:** Matricea Hub nu poate afișa culori RGB — afișează cifre. Mapare vocală înainte de joc: `1 = red`, `2 = green`, `3 = blue`.

- Robot spune un cuvânt de culoare (*„red”*), dar afișează altă cifră pe matrice (ex. **2** = green).
- Copilul trebuie să spună culoarea cifrei văzute pe matrice, nu cuvântul auzit.
- Seturi scurte pentru a evita frustrarea.

**Valoare terapeutică:**

- antrenează **inhibiția interferenței**;
- crește atenția la stimulul relevant;
- relevant pentru dificultăți de control executiv.

**Feasibility:** ★★★☆☆

**Metrici:** `congruent_trials`, `incongruent_trials`, `stroop_errors`, `reaction_ms`

---

### 3.15 Problem-solving cu hint gradual (scaffolded help)

**Procedeu inspirat:** principii de **scaffolding** / zona proximală de dezvoltare (Vygotsky).

**Procedeu:**

- La sarcină greșită, robotul nu dă direct răspunsul.
- Oferă 3 niveluri de hint: general -> specific -> demonstrație.
- Marchează nivelul minim de ajutor necesar.

**Valoare terapeutică:**

- dezvoltă autonomia în rezolvare;
- reduce dependența de ajutor imediat;
- oferă terapeutului indicator de independență cognitivă.

**Feasibility:** ★★★★★

**Metrici:** `hint_level_used`, `success_after_hint`, `independence_score`

---

### 3.16 Estimare temporală (time perception game)

**Procedeu inspirat:** exerciții de **time estimation** (funcții executive).

**Procedeu:**

- Robot spune: „When you think 10 seconds passed, say stop.”
- Repetă pe 5 s, 10 s, 20 s.
- Compară estimarea copilului cu timpul real.

**Valoare terapeutică:**

- antrenează autoreglarea ritmului intern;
- util pentru planificarea activităților și tranziții;
- scade impulsivitatea prin conștientizarea timpului.

**Feasibility:** ★★★★☆

**Metrici:** `target_seconds`, `estimated_seconds`, `absolute_error_s`

---

### 3.17 Recunoaștere prosodie (tone of voice)

**Procedeu inspirat:** antrenament de **recunoaștere afectivă vocală**.

**Procedeu:**

- Robot redă aceeași propoziție în tonuri diferite (happy, sad, angry, calm).
- Copilul identifică tonul.
- Opțional: copilul repetă propoziția în același ton.

**Valoare terapeutică:**

- îmbunătățește procesarea indiciilor sociale non-verbale;
- crește empatia și înțelegerea stărilor celuilalt;
- util pentru copiii cu dificultăți de pragmatica limbajului.

**Feasibility:** ★★☆☆☆ (TTS expresiv limitat)

**Metrici:** `prosody_label`, `correct_identification_rate`, `imitation_score`

---

### 3.18 Story sequencing (ordine logică în 3 pași)

**Procedeu inspirat:** evaluare de **organizare narativă** și secvențiere.

**Procedeu:**

- Robot oferă 3 evenimente scurte amestecate.
- Copilul spune ordinea corectă (început -> mijloc -> final).
- Robot verifică și explică blând de ce ordinea contează.

**Valoare terapeutică:**

- susține coerența narativă și planificarea verbală;
- ajută la înțelegerea cauză-efect;
- relevant pentru comunicare socială și școlară.

**Feasibility:** ★★★★☆

**Metrici:** `sequence_correct`, `reorder_attempts`, `narrative_coherence_score`

---

### 3.19 Toleranță la schimbare (routine switch)

**Procedeu inspirat:** expunere gradată la **schimbări de rutină**.

**Procedeu:**

- Robot rulează o rutină previzibilă 2-3 ture.
- Introduce o schimbare mică anunțată („Now we do it in reverse”).
- Măsoară adaptarea fără escaladare.

**Valoare terapeutică:**

- reduce rigiditatea comportamentală;
- crește flexibilitatea la tranziții;
- foarte util în ASD pentru transfer la viața zilnică.

**Feasibility:** ★★★★★

**Metrici:** `switch_event`, `adaptation_time_s`, `distress_markers`

---

### 3.20 Auto-instrucțiuni ghidate (self-talk routine)

**Procedeu inspirat:** tehnici CBT/educaționale de **self-instruction** (Meichenbaum, adaptat).

**Procedeu:**

- Robot modelează verbal pașii: „Stop. Think. Choose. Do.”
- Copilul repetă formula înainte de task.
- După câteva sesiuni, robotul cere copilului să inițieze singur formula.

**Valoare terapeutică:**

- îmbunătățește metacogniția și controlul impulsului;
- crește auto-eficacitatea în task-uri dificile;
- oferă strategie transferabilă acasă/școală.

**Feasibility:** ★★★★★

**Metrici:** `self_prompt_used`, `task_success_after_prompt`, `independent_initiation_rate`

---

## 4. Matrice comparativă — prioritate implementare

| # | Funcție | Valoare terapeutică | Efort | Prioritate licență |
|---|---------|---------------------|-------|-------------------|
| 1 | Build the Model (ESP32-CAM) | ★★★★★ | mediu | **P1** |
| 2 | Memory Lights culori | ★★★★☆ | mediu | **P1** |
| 3 | Stop & Go | ★★★★☆ | mic | **P1** |
| 4 | Raport sesiune terapeut | ★★★★★ | mic | **P1** |
| 5 | Check-in emoțional | ★★★★☆ | mic | P2 |
| 6 | Rutine sociale scriptate | ★★★★☆ | mic | P2 |
| 7 | Turn-taking | ★★★★☆ | mic | P2 |
| 8 | Pauză reglare automată | ★★★★★ | mic | P2 |
| 9 | Joint attention | ★★★★★ | mare | P3 |
| 10 | Flexibilitate reguli (mini-WCST) | ★★★☆☆ | mare | P3 |
| 11 | Imită emoția + CAM | ★★★★☆ | mare | P3 |
| 12 | Delayed gratification | ★★★☆☆ | mediu | P3 |

---

## 5. Mapare hardware

| Resursă | Jocuri / procedee |
|---------|-------------------|
| Matrice LED Hub (`main.py`) | modele Build the Model, Stop&Go, Memory Lights, countdown |
| Motoare brațe B/E, roți C/D, cap F | feedback, dans, joint attention, high-five |
| HuskyLens (I2C pe ESP) | ID fixe, rapid, offline |
| ESP32-CAM + `vision_esp32cam_bridge.py` | verificare construcții, culori, emoții față, flexibilitate |
| Voce STT/TTS (Gemini + Cloud TTS) | check-in, rutine sociale, ghicire emoții |
| MQTT + `trisense/brain.py` | orchestrare, stări, metrici |

---

## 6. Stări noi sugerate (`trisense/states.py`)

| Stare propusă | Activitate |
|---------------|------------|
| `BUILD_MODEL` | afișare model + timer 30s + verificare CAM |
| `MEMORY_LIGHTS` | secvență culori + răspuns copil |
| `STOP_GO` | trial inhibiție |
| `MOOD_CHECKIN` | check-in emoțional |
| `SOCIAL_SCRIPT` | rutină socială fixă |
| `REGULATION_BREAK` | pauză respirație forțată |

---

## 7. Referințe conceptuale (bibliografie licență)

- LeGoff, D. — *Lego-Based Therapy*
- Gray, C. — *Social Stories*
- Teste executive inspirate: Tower of Hanoi, Go/No-Go (literatură neuropsihologie pediatrică)
- WRO 2025 — AI enabling robots to improve daily living
- Raport echipă: *Project Report 2.0 — TriSense* (observational learning, 6 jocuri terapeutice)
- ASM Smart Clinic / LBT România — context validare practică

---

## 8. Următorii pași recomandați

1. Alegere **2 funcții P1** pentru implementare (ex. Build the Model + Raport sesiune).
2. Definire stări noi în `RobotState` și handler-e în `brain.py`.
3. Extindere `MetricsLogger` cu câmpuri per activitate (`activity`, `session_id`, `success`).
4. Formulare în disertație: scop terapeutic, limite etice, fără claim de diagnostic clinic.

---

*Document TriSense — funcționalități posibile pentru licență / WRO Romania.*
