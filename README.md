# Seedance Seam Fix

Behebt periodische "Ruckler" in KI-generierten Videos (z. B. Seedance 2.5), die
durch Chunk-Grenzen in der Video-Diffusions-Generierung entstehen — **kein**
Problem mit doppelten/fehlenden Frames, sondern ein echter, kleiner
Bewegungssprung an regelmäßigen Stellen im Video (bei Seedance meist alle ~24
Frames / ~1 Sekunde).

Der Fix: Sprungstellen automatisch erkennen, dort per KI (RIFE) den optimalen
Zwischenframe berechnen und **genau einen Frame** einfügen. Das Video wird
dadurch pro Sprungstelle um 1 Frame länger, der Sprung verteilt sich auf zwei
kleinere Bewegungsschritte statt einen abrupten.

## Voraussetzungen

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/download.html) (im PATH verfügbar)
- [rife-ncnn-vulkan](https://github.com/nihui/rife-ncnn-vulkan/releases) —
  portables Kommandozeilen-Tool, kein CUDA/PyTorch nötig, läuft auf
  Windows/Linux/macOS über Vulkan

## Installation

```bash
git clone <dieses-repo>
cd seedance-seam-fix

python3 -m venv venv
# macOS/Linux:
source venv/bin/activate
# Windows (PowerShell — falls Execution Policy blockt: erst einmalig
# `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`):
venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt`:
```
opencv-python-headless
numpy
```

RIFE herunterladen und entpacken (z. B. nach `./rife-ncnn-vulkan/`):
https://github.com/nihui/rife-ncnn-vulkan/releases
Das Zip enthält die ausführbare Datei (`rife-ncnn-vulkan` bzw. `.exe`) sowie
die Modellordner (z. B. `rife-v4.6`). Portabel, keine weitere Installation
nötig.

## Nutzung

### Windows: Desktop-Launcher

`Seedance Frame Fix.cmd` auf dem Desktop per Doppelklick starten und ein Video
auswaehlen; alternativ eine Videodatei auf den Launcher ziehen. Das Ergebnis
landet neben der Eingabe als `<name>_fixed.mp4`. Bereits vorhandene Ergebnisse
werden durch nummerierte Dateinamen geschuetzt. Ohne erkannte Sprungstellen
wird keine neue Datei erzeugt.

Der Launcher verwendet `.venv\Scripts\python.exe` und das lokal heruntergeladene Modell
`rife-v4.6`. FFmpeg und FFprobe muessen im PATH liegen. Zum erneuten Einrichten:

```powershell
uv venv --python 3.12 --seed .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_desktop_launcher.ps1
```

Der Installer ueberschreibt keinen vorhandenen Desktop-Launcher. Alternativ
laesst sich `launch.ps1` direkt ausfuehren.

### 1. Sprungstellen finden (optional, zur Kontrolle)

```bash
python3 find_seams.py input.mp4
```

Analysiert die Bewegung zwischen aufeinanderfolgenden Frames und meldet
auffällige Sprünge sowie eine erkannte Periodizität, z. B.:

```
22 auffällige Sprungstellen gefunden (Übergang Frame i -> i+1):
  Frame    95 ->    96   (t=  3.96s)   score=7.60
  ...
Wahrscheinliche Periodizität: alle ~24 Frames (~1.00s bei 24.0 fps)
```

Rohdaten landen zusätzlich in `score_per_frame.csv` zum manuellen Nachschauen.

### 2. Reparieren (Hauptscript)

```bash
python3 insert_best_frame.py input.mp4 output.mp4 \
  --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe \
  --rife-model rife-ncnn-vulkan/rife-v4.6
```

Das Script:
1. erkennt Sprungstellen automatisch (gleiche Logik wie `find_seams.py`),
2. erzeugt pro Sprungstelle mehrere RIFE-Kandidatenframes an verschiedenen
   Zeitpunkten zwischen Frame i und i+1,
3. wählt den Kandidaten, bei dem der Bewegungssprung auf beide Seiten am
   gleichmäßigsten verteilt ist,
4. fügt **genau diesen einen Frame** ein (Video wird dadurch um die Anzahl
   der Sprungstellen länger),
5. encodet das Ergebnis einmalig verlustarm (CRF, Standard 14) und streckt
   den Ton proportional, damit er synchron bleibt.

**Wichtige Optionen:**

| Flag | Bedeutung |
|---|---|
| `--candidates N` | Anzahl Kandidaten-Zeitpunkte pro Sprungstelle (default 7) |
| `--frames 95,119,...` | Sprungstellen manuell vorgeben statt Auto-Erkennung |
| `--threshold` | Empfindlichkeit der Auto-Erkennung (kleiner = empfindlicher) |
| `--crf` | Finale Videoqualität, niedriger = besser (default 14) |
| `--workdir` | Ordner für Zwischendateien (default `<output>_work/`) |
| `--clean` | Workdir vor dem Lauf leeren (z. B. nach geänderten Sprungstellen) |
| `--no-stretch-audio` | Ton nicht strecken, bleibt unverändert |
| `--include-scene-cuts` | Automatischen Szenenschnitt-Filter deaktivieren |

**Zwischendateien** (extrahierte Originalframes, alle getesteten Kandidaten,
finale Sequenz) landen in `<output>_work/` und werden **nicht** automatisch
gelöscht — praktisch, um einzelne Kandidaten manuell zu prüfen oder
nachzubessern, und um bei einem erneuten Lauf die teure Frame-Extraktion zu
überspringen.

Der Cache wird nur wiederverwendet, wenn der SHA-256-Fingerabdruck der Eingabe
und die vollstaendige Frame-Dateiliste mit Dateigroessen passen. Eine abgebrochene
Extraktion wird neu gestartet. `--clean` erneuert nur verwaltete Unterordner;
andere Dateien im Workdir bleiben erhalten. Nicht leere Arbeitsordner ohne
Projektmarkierung (auch aus alten Versionen) werden abgelehnt: dafuer einen
neuen Workdir angeben. Eingabe, Ausgabe und Projekt duerfen nicht im Workdir liegen.
Kandidaten liegen getrennt unter `candidates/seam_<Index>/`; Indizes sind nullbasiert.

Die Periodenschaetzung verlangt mindestens drei gleiche Abstaende mit mindestens
60 Prozent Anteil und zeigt diesen Anteil an. Sie beweist keine Modell-Fenstergroesse.

### Weitere Scripts im Repo (ältere/alternative Ansätze)

- `fix_seams.py` — ersetzt (statt einzufügen) die 2 Frames an jeder
  Sprungstelle, Video bleibt gleich lang. Führt bei starken Sprüngen zu
  sichtbar abrupteren Übergängen als `insert_best_frame.py`, da die komplette
  Bewegung in dieselbe kurze Zeitspanne gepresst wird.
- `insert_seams.py` — fügt pauschal `factor - 1` Frames pro Sprungstelle ein
  (kein Auswahlschritt). Vorläufer von `insert_best_frame.py`.

Empfehlung: **`insert_best_frame.py` verwenden**, liefert bisher die besten
Ergebnisse (siehe `HANDOVER.md` für Details zur Entwicklungsgeschichte).

## Bekannte Einschränkungen

- Ein konservativer Szenenschnitt-Filter laesst Uebergaenge mit gleichzeitig
  grosser Pixeldifferenz und stark abweichender Farbverteilung aus. Die Heuristik
  kann Schnitte uebersehen und starke Lichtwechsel falsch einordnen. Mit
  `--include-scene-cuts` abschaltbar; explizite `--frames` umgehen den Filter.
- Bei sehr großem Bewegungssprung (Score weit über dem Rest, typischerweise
  gegen Ende einer langen Seedance-Generierung durch akkumulierenden Drift)
  kann selbst der beste RIFE-Kandidat den Sprung nicht vollständig kaschieren.

Mehr Kontext, offene Fragen und Ideen für Weiterentwicklung: siehe
`HANDOVER.md`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\smoke_pipeline.py
```

Der zweite Test benoetigt FFmpeg, FFprobe und das lokal installierte Windows-RIFE.
Er erzeugt ein kurzes Testvideo unter `.test-output/`, prueft Framezahl und Audio
und fuehrt die Verarbeitung erneut aus, um die Cache-Wiederverwendung zu pruefen.

## Dateien im oeffentlichen Repository

Virtuelle Umgebungen, lokale Einstellungen, Videos, generierte Frames und
heruntergeladene RIFE-Binaerdateien/Modelle werden nicht versioniert.
RIFE vor dem ersten Start wie unter Installation beschrieben herunterladen und
nach `rife-ncnn-vulkan/` entpacken. Dessen README und Lizenz bleiben im Repository.
Tests erzeugen ihre Videodaten lokal; private Beispielvideos sind nicht erforderlich.
