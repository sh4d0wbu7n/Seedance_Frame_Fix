# Handover / Kontext für zukünftige Weiterentwicklung

## Realvideo-Evaluation: Vorgehen, Ergebnis und Begruendung

Getestet wurde lokal mit `Seedance_long.mp4`: 1920x1080, 24 fps, 601 Frames,
25.041667 Sekunden Videodauer und vorhandener Tonspur. Die Quelldatei ist privat
und wird nicht eingecheckt. Die Bezeichnung dient nur zur Zuordnung des lokalen
Tests; das Programm enthaelt weder Dateinamen-Sonderfaelle noch feste Sprung-Indizes.

### Was wurde getestet und warum?

1. **Original und unveraenderten Algorithmus vermessen.** FFprobe pruefte
   Framezahl, Bildrate, Aufloesung und Audio. `find_seams.py` lieferte Rohscores;
   ein vollstaendiger Referenzlauf mit sieben RIFE-Kandidaten pro Treffer wurde
   erzeugt. Das schafft einen Vergleich vor jeder Aenderung und verhindert,
   dass neue Ergebnisse nur gegen einen subjektiven Eindruck bewertet werden.
2. **Treffer und ausgelassene Spitzen untersuchen.** Kontaktbilder zeigten
   benachbarte Originalframes; lokale Medianwerte, Z-Scores und Farbverteilungen
   halfen, schwache statistische Ausreisser von groesseren Bewegungswechseln
   abzugrenzen. Zwei Treffer bei Indizes 122 und 278 lagen nur ca. 6 bzw.
   4 Prozent ueber dem lokalen Median. Die kleine lokale Streuung machte ihren
   Z-Score trotzdem auffaellig. Vier weitere lokale Maxima (23, 47, 71, 575)
   lagen auf dem klaren 24-Frame-Raster, wurden aber vom festen Z-Schwellwert
   verpasst. Diese Beobachtung begruendete Mindestanstieg und Perioden-Ergaenzung.
3. **Allgemeine Regeln statt videofester Korrekturen implementieren.** Mindestens
   10 Prozent relativer Anstieg fuer normale Treffer. Periodische Ergaenzung
   erst ab vier starken Treffern, drei gleichen Abstaenden mit mindestens
   60 Prozent Anteil und mindestens 80 Prozent Phasenuebereinstimmung.
   Ein ergaenzter Punkt braucht weiterhin ein lokales Maximum, mindestens
   15 Prozent relativen und 0.5 Graustufen absoluten Anstieg sowie Z >= 1
   (bzw. den explizit niedrigeren Schwellwert). Rasterposition allein reicht
   nicht. Die gemeldete Perioden-Konfidenz benutzt nur unabhaengig erkannte
   starke Treffer, damit ergaenzte Punkte sie nicht kuenstlich erhoehen.
4. **Kandidatenwahl separat kontrollieren.** Im Referenzlauf gewann an allen
   22 Stellen t=0.5. Daher zuerst ein schneller verbesserter Lauf mit einem
   Kandidaten. Die 20 gemeinsamen Stellen waren byte-identisch mit den jeweils
   besten Referenzkandidaten. Anschliessend auch die vier neuen Stellen mit
   sieben Kandidaten pruefen: Bei Index 23 gewann t=0.375, bei den anderen
   t=0.5. Deshalb sieben Kandidaten als Standard beibehalten. Die finale
   Sequenz wurde aus diesen bereits berechneten besten Kandidaten aufgebaut
   und einmal aus PNGs encodiert, ohne erneute verlustbehaftete Zwischenrunde.
5. **Das fertige Video pruefen.** FFprobe bestaetigte 625 Frames bei 24 fps
   (26.041667 Sekunden); Audio war vorhanden und ca. 26.03 Sekunden lang.
   FFmpeg decodierte Bild und Ton vollstaendig ohne gemeldete Fehler. Die
   Uebergangsscores wurden nochmals am encodierten Ergebnis gemessen, um
   Kandidatenqualitaet und Encoding nicht zu verwechseln. Der SHA-256-Abgleich
   mit dem Extraktionsmanifest bestaetigte das unveraenderte Original.
6. **Regressionen absichern.** Zehn Unittests deckten Cache-Invalidierung,
   abgebrochene Extraktion, Workdir-Schutz, Argumente, getrennte Kandidaten,
   Pad/Randbehandlung, Szenenschnitt-Heuristik, Perioden-Konfidenz, schwache
   Ausreisser und evidenzpflichtige periodische Ergaenzung ab. Der synthetische
   FFmpeg/RIFE-Smoke-Test pruefte 24 -> 26 Frames, Audio, Cache-Wiederverwendung
   und den neuen JSON-Reparaturbericht. Alle Tests bestanden.

### Ergebnis und Grenzen der Aussage

Der Referenzlauf fuegte 22 Frames ein (623 insgesamt). Die verbesserte Erkennung
entfernte zwei schwache Treffer und ergaenzte vier Spitzen: 24 Einfuegungen,
625 Frames insgesamt. Der jeweils groessere der beiden verbleibenden
Uebergangsscores sank im Mittel um 30.8 Prozent an den PNG-Kandidaten und um
28.7 Prozent im fertig encodierten Video (Spanne 18.5 bis 42.8 Prozent).
Diese Zahlen vergleichen die reparierten Stellen mit ihren **Originalspruengen**,
nicht mit dem schon reparierten Referenzvideo.

Die Metrik ist mittlere Graustufen-Pixeldifferenz nach Skalierung auf 320 Pixel
Breite und Blur. Sie ist kein unabhaengiges Wahrnehmungsmodell und bevorzugt
gegebenenfalls auch weichere Bilder. Modellseitig erfolgte eine Sichtpruefung
von Kontaktbildern, keine vollstaendige Echtzeit-Wiedergabe. Der Nutzer bewertete
das gelieferte Video anschliessend ausdruecklich als sehr gutes Ergebnis.
Die neuen Schwellen wurden an **einem** Realvideo plus synthetischen Tests
geprueft. Die README-Startwerte fuer andere Shot-Typen sind begruendete Vorschlaege,
keine gemessenen Presets. Globale Audiostreckung bleibt eine Naeherung.

### Reproduzierbare Befehle

Voraussetzung: Projekt-venv, FFmpeg/FFprobe und lokal entpacktes RIFE v4.6.
Aus dem Projektordner ausfuehren; andere Ausgabe-Dateinamen waehlen, falls
bereits eigene Ergebnisse existieren.

```powershell
# Verhalten vor der neuen Mindeststaerke und Perioden-Ergaenzung:
.\.venv\Scripts\python.exe insert_best_frame.py Seedance_long.mp4 Seedance_long_baseline.mp4 --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe --rife-model rife-ncnn-vulkan/rife-v4.6 --min-relative-jump 0 --no-periodic-recovery --candidates 7
# Neue Standarderkennung und finale Kandidatenwahl:
.\.venv\Scripts\python.exe insert_best_frame.py Seedance_long.mp4 Seedance_long_improved.mp4 --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe --rife-model rife-ncnn-vulkan/rife-v4.6 --candidates 7
# Lokale Messdaten/Kontaktbilder und technische Pruefung:
.\.venv\Scripts\python.exe evaluate_video.py Seedance_long.mp4 --output .test-output/evaluation --candidates Seedance_long_improved_work/candidates
ffprobe -v error -show_streams -show_format -of json Seedance_long_improved.mp4
ffmpeg -v error -i Seedance_long_improved.mp4 -f null -
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests/smoke_pipeline.py
```

`evaluate_video.py` vergleicht Original und vorhandene PNG-Kandidaten; die
Messung nach Encoding wurde fuer diesen Test separat durch Zuordnung der
eingefuegten Frames vorgenommen. Sie ist nicht automatisch Teil dieses Tools.
`repair_report.json` enthaelt die Kandidatenmetrik und Laufparameter.

Nach Abschluss wurden auf Nutzerwunsch Testausgaben entfernt: beide erzeugten
Vergleichsvideos, ihre `_work`-Ordner, `.test-output/` mit Kontaktbildern,
Messdateien und einmaligen Auswertungsscripts, `score_per_frame.csv` und
Python-Bytecode-Caches im Projekt/Testordner. Originalvideo, `.venv`, RIFE und
die wiederverwendbaren Test-/Evaluationsscripts bleiben erhalten.

## Aktualisierung 2026-09-22

Ein anschliessender Realvideo-Vergleich ergab zwei sehr schwache Z-Score-Treffer
bei nur 4-6 Prozent Bewegungsanstieg sowie vier ausgelassene lokale Spitzen auf
einem stabilen 24-Frame-Raster. Die gemeinsame Erkennung in `seam_utils.py`
verlangt jetzt mindestens 10 Prozent relativen Anstieg und kann evidenzgestuetzt
periodische Spitzen ergaenzen (abschaltbar). Die vier Scripts verwenden dieselbe
Erkennung; ihre Kopien wurden entfernt. `evaluate_video.py` und
`repair_report.json` erlauben nachvollziehbare lokale Vergleiche ohne private
Videodaten zu versionieren. Die neuen Schwellen sind an einem Realvideo plus
synthetischen Regressionstests geprueft, nicht an einem breiten Benchmark.

Die folgenden historischen Abschnitte beschreiben den urspruenglichen Stand.
Inzwischen umgesetzt: abgesicherter Frame-Cache mit Eingabe-SHA-256 und
Abschlussmanifest, markierte Workdirs mit begrenzter Bereinigung, getrennte
Kandidaten je Sprung, CLI-Validierung, Perioden-Mindestkonfidenz sowie korrekte
`--pad`-Zeitpunkte inklusive Randbehandlung. `fix_seams.py` erzeugt Ersatzframes
zuerst aus unveraenderten Originalen. Die alten Scripts verwenden bei
`--keep-frames` neue eindeutige Ordner, damit keine alten Restframes bleiben.

Alle vier Scripts nutzen `seam_utils.py` fuer gemeinsame Validierung bzw.
Szenenschnitt-Heuristik; sie sind daher nicht mehr einzeln kopierbar.
Die konservative Schnitt-Heuristik ist standardmaessig bei Auto-Erkennung aktiv,
mit `--include-scene-cuts` abschaltbar; manuelle `--frames` haben Vorrang.
Sie ist noch nicht an einem Repraesentativsatz echter Seedance-Videos kalibriert.
Regressionstests und ein expliziter FFmpeg/RIFE-Smoke-Test liegen unter `tests/`.
Windows-Start ueber `launch.ps1` bzw. installierten Desktop-Launcher.

Dieses Dokument ist für eine zukünftige LLM-Session (oder dich selbst in ein
paar Monaten) gedacht, um das Projekt ohne erneutes Durchprobieren aller
Sackgassen fortzusetzen. Bitte komplett lesen, bevor du etwas änderst — die
"naheliegenden" ersten Ideen wurden hier bereits ausprobiert und verworfen,
mit nachvollziehbarem Grund.

## Das Problem (Ausgangslage)

Videos, generiert mit Seedance 2.5, haben ein periodisches "Ruckeln" — ca.
alle 24 Frames (bei 24fps ≈ jede Sekunde) einen sichtbar größeren
Bewegungssprung als zwischen den umliegenden Frames.

## Was NICHT die Ursache ist (bereits widerlegt)

1. **Keine doppelten/gehaltenen Frames.** Erste Hypothese war, dass Seedance
   wie manche andere Modelle intern Frames hält/dupliziert. Tools wie
   "SeeFrame" (die nach echten Bild-Duplikaten suchen) finden hier nichts —
   zu Recht, denn es liegen keine vor. Frame-für-Frame-Inspektion durch den
   Nutzer bestätigte: es gibt an den Sprungstellen keine identischen
   Nachbarbilder, nur einen größeren Bewegungssprung.

2. **Nicht einfach durch globale Interpolation lösbar** (`ffmpeg minterpolate`
   übers ganze Video, oder RIFE übers ganze Video mit fixem Faktor) —
   funktioniert im Prinzip, ist aber unnötig aufwändig/langsam, wenn nur
   ~20-30 von ~600 Frames betroffen sind. Der gezielte Ansatz (nur an den
   erkannten Sprungstellen rechnen) liefert **identische** Qualität, weil
   RIFE rein paarweise arbeitet und keinen Kontext über den Rest des Videos
   nutzt (siehe Abschnitt "Wie RIFE funktioniert" unten). Kein Grund, global
   zu interpolieren.

## Die tatsächliche Ursache

Video-Diffusionsmodelle wie Seedance generieren nicht am Stück, sondern in
zeitlichen Chunks/Fenstern (z. B. alle ~24 Frames ein neues Fenster). An den
Chunk-Grenzen hat das Modell nur eingeschränkten Kontext zum vorherigen
Abschnitt, wodurch die Bewegung dort leicht "springt" — ein echter, wenn auch
kleiner, Inhaltssprung, kein Kompressions-/Kodierungsartefakt.

Bestätigt durch: `find_seams.py` misst pro Frame-Übergang die
Bewegungsstärke (mittlere Pixel-Differenz nach Weichzeichnung, robust gegen
normales Rauschen) und findet Ausreißer per lokalem robustem Z-Score. Bei
einem echten Testvideo kam eine fast perfekte Periodizität von 24 Frames
heraus, over 20 Sprungstellen im Video verteilt. Auffällig: der Score steigt
über die Videodauer an (von ~7 auf ~13) — typisch für autoregressive
Generierung, bei der sich Drift zwischen den Chunks akkumuliert.

**Cave­at:** Mindestens eine "Sprungstelle" im Test stellte sich als
tatsächlicher **Szenenschnitt** heraus (Wechsel von schnellem FPV-Flug zu
einer komplett anderen, statischen Vogelperspektiven-Szene), nicht als
Chunk-Artefakt. Die automatische Erkennung unterscheidet das aktuell nicht —
sie misst nur "großer Bewegungssprung", nicht die Ursache. Bei einer Sequenz
aus mehreren zusammengeschnittenen Shots (statt einem durchgehenden Take)
können echte Schnitte fälschlich als Reparaturkandidat markiert werden. Für
solche Stellen ist Frame-Einfügen falsch (es gibt keinen fließenden Übergang
zu erzeugen). **Offene Aufgabe:** Schnitt vs. Chunk-Artefakt automatisch
unterscheiden (Idee: ein echter Schnitt hat i.d.R. eine viel größere
absolute Differenz UND keine Ähnlichkeit in Histogramm/Farbverteilung
zwischen den beiden Seiten, während ein Chunk-Sprung "in derselben Szene"
bleibt).

## Entwicklungsverlauf der Lösung (chronologisch, mit Begründung)

1. **`fix_seams.py` v1 — Farneback Optical Flow, Frames ersetzen.**
   Ersetzte die 2 Frames an jeder Sprungstelle durch Optical-Flow-Interpolation
   (klassisch, `cv2.calcOpticalFlowFarneback`) zwischen den Frames davor/danach.
   **Ergebnis: schlecht.** Das Testvideo ist eine schnelle FPV-Drohnenaufnahme
   über Heidekraut — große, schnelle, sich wiederholende Textur im Vordergrund.
   Genau der Worst Case für klassischen Optical Flow: er verwechselt
   Grasbüschel untereinander, der Horizont/Bäume wirken in den interpolierten
   Frames sichtbar wellig/verzerrt. **Lektion: klassischer Optical Flow
   (Farneback/Lucas-Kanade) taugt nicht für große/schnelle Bewegung mit
   repetitiver Textur.**

2. **`fix_seams.py` v2 — RIFE statt Farneback, weiterhin Frames ersetzen.**
   RIFE (trainiertes Netz, siehe unten) statt klassischem Flow. Deutliche
   Verbesserung der lokalen Bildqualität an den Sprungstellen. **Aber:** der
   Gesamteindruck des Videos blieb "unsauber". Ursache gefunden: das Script
   schrieb ALLE Frames (auch die ~580 unberührten) nochmal durch OpenCVs
   `VideoWriter` mit dem schwachen `mp4v`-Codec, bevor ffmpeg final encodete
   — eine komplette zusätzliche verlustbehaftete Kompressionsrunde über das
   GANZE Video, nicht nur die reparierten Stellen. **Lektion: bei
   Frame-genauer Videobearbeitung nie unnötig über einen zusätzlichen
   verlustbehafteten Video-Codec-Zwischenschritt gehen — lieber verlustfrei
   als PNG extrahieren, gezielt einzelne Dateien ersetzen, dann EINMAL final
   encodieren.**

3. **`fix_seams.py` v3 — PNG-Pipeline, weiterhin Frames ersetzen.**
   Qualitätsproblem aus Schritt 2 behoben. **Nutzer-Feedback: ruckelt
   weiterhin.** Ursache: Ersetzen von exakt 2 Frames zwingt die komplette
   (teils recht große) Bewegungsänderung in dieselbe kurze Zeitspanne wie im
   Original — bei einem echten, größeren Inhaltssprung reicht das nicht, egal
   wie gut das Interpolationsmodell ist. **Lektion: bei echten
   Inhaltssprüngen (nicht nur Kompressionsartefakten) hilft Ersetzen mit
   gleicher Framezahl nur begrenzt — die Zeitspanne selbst muss gestreckt
   werden.**

4. **`insert_seams.py` — Frames einfügen statt ersetzen (Faktor 4).**
   Automatisiert den manuellen Ansatz des Nutzers: statt zu ersetzen, an
   jeder Sprungstelle 3 zusätzliche RIFE-Frames einfügen (Video wird länger).
   Verteilt den Sprung über mehr Zeit → wirkt subjektiv smoother, auch bei
   echtem Inhaltssprung. **Funktionierte prinzipiell**, aber der Nutzer wollte
   ursprünglich ohnehin nur 1 Frame pro Stelle einfügen — Faktor 4 diente ihm
   nur dazu, beim manuellen Aussuchen mehr Auswahl zu haben.

5. **`insert_best_frame.py` — aktueller Stand, vom Nutzer als bislang bestes
   Ergebnis bestätigt.** Statt pauschal mehrere Frames einzufügen: mehrere
   RIFE-Kandidaten an verschiedenen Zeitpunkten generieren (Standard: 7,
   Zeitpunkte 1/8 bis 7/8 zwischen Frame i und i+1), dann den Kandidaten
   wählen, bei dem der verbleibende Bewegungssprung auf beide Seiten (i→Kandidat
   und Kandidat→i+1) am gleichmäßigsten verteilt ist (Minimierung des
   *größeren* der beiden Restsprünge). Nur dieser eine Frame wird eingefügt.
   Das ist die aktuelle Empfehlung, siehe `README.md`.

## Wie RIFE funktioniert (für Kontext, falls das Modell mal getauscht wird)

RIFE (Real-Time Intermediate Flow Estimation) ist ein trainiertes CNN, das
aus zwei Bildern (Frame A, Frame B) direkt den Bewegungsfluss zu einem
Zeitpunkt t schätzt — ohne separaten klassischen Optical-Flow-Schritt:
1. IFNet schätzt in mehreren Auflösungsstufen (grob → fein) den Fluss von A
   und B zum Zeitpunkt t.
2. Beide Bilder werden anhand dieses Flusses zum Zeitpunkt t verzogen (warped).
3. Ein Fusionsnetz kombiniert beide verzogenen Bilder inkl. einer gelernten
   Occlusion-Maske (was in A sichtbar ist, in B aber verdeckt, und umgekehrt).

**Wichtige Eigenschaft:** RIFE ist rein paarweise, hat keinerlei Kontext über
das restliche Video. Deshalb ist gezieltes Rechnen nur an den Sprungstellen
(statt globaler Interpolation) verlustfrei bezüglich Qualität — nur schneller.
`rife-ncnn-vulkan` (https://github.com/nihui/rife-ncnn-vulkan) ist die
portable Kommandozeilen-Implementierung, die hier verwendet wird (kein
CUDA/PyTorch-Runtime nötig, läuft via Vulkan auf CPU/GPU).

## Offene Punkte / Ideen für Weiterentwicklung

- **Szenenschnitte von Chunk-Sprüngen unterscheiden** (siehe oben). Bisher
  keine automatische Unterscheidung implementiert.
- **Auswahlkriterium für den "besten" Frame ist ein Proxy, kein perfektes
  Maß.** Aktuell: mittlere Pixel-Differenz nach Weichzeichnung/Downscaling
  auf 320px Breite (schnell, aber grob). Bessere Kandidaten für die
  Bewertung: strukturähnlichkeitsbasierte Metriken (SSIM/LPIPS) oder ein
  echter Optical-Flow-Magnitude-Vergleich (z. B. RAFT) statt simpler
  Pixel-Differenz — könnte robuster gegen Helligkeits-/Kontraständerungen
  sein, die keine echte Bewegung sind.
- **Ton-Synchronität ist eine Näherung.** `--stretch-audio` streckt den
  gesamten Ton gleichmäßig um den Faktor `orig_duration / new_duration`. Das
  funktioniert gut, WEIL die Sprungstellen bei Seedance recht regelmäßig über
  das Video verteilt sind (periodisch alle ~24 Frames) — bei unregelmäßig
  verteilten Sprüngen wäre eine gleichmäßige Streckung ungenauer. Für
  Videos mit wichtigem lippensynchronem Ton (Dialog) müsste man stattdessen
  pro Einfügepunkt einen kurzen stillen Frame/Crossfade im Audio einfügen,
  statt global zu strecken.
- **Kein automatischer Vergleichstest/Regressionstest.** Bisher wird jedes
  Ergebnis nur visuell vom Nutzer geprüft (Frame-Export + Sichtprüfung). Für
  systematischere Weiterentwicklung wäre ein kleines Set von
  Referenzvideos (mit bekannten Sprungstellen) samt automatisierter
  Bewertung (z. B. "Restsprung-Score vor/nach Fix") sinnvoll.
- **`--candidates` höher setzen kostet linear mehr RIFE-Aufrufe** (2x pro
  Kandidat momentan? — nein, 1x pro Kandidat, aber die Kosten steigen
  trotzdem linear mit der Anzahl Sprungstellen × Kandidaten). Für sehr lange
  Videos mit vielen Sprungstellen ggf. Parallelisierung/Batching einbauen
  (rife-ncnn-vulkan unterstützt Verzeichnis-Modus mit mehreren
  GPU-Threads, `-j load:proc:save`, bisher ungenutzt).
- **Sehr große Sprünge (Score weit über dem Rest, siehe README) werden vom
  aktuellen Ansatz nicht vollständig gelöst.** Denkbare nächste Schritte:
  mehrere Frames gezielt nur an DIESEN besonders schlimmen Stellen einfügen
  (Hybrid aus `insert_seams.py`-Logik mit variablem Faktor je nach
  Sprung-Score, statt pauschal 1 Frame überall).

## Technische Details / Umgebung

- Python 3, Abhängigkeiten: `opencv-python-headless`, `numpy` (siehe
  `requirements.txt`).
- Frame-Erkennung: robuster lokaler Z-Score auf mittlere Graustufen-Pixel-
  differenz (Fenster von 15 Frames, Median + MAD statt Mittelwert/Std, um
  robust gegen die Sprünge selbst zu sein).
- Alle Scripts sind bewusst eigenständig (keine gemeinsame Library) gehalten,
  damit sie einzeln kopierbar/nachvollziehbar bleiben. Bei weiterer
  Verzweigung lohnt sich ein Refactoring in ein gemeinsames Modul
  (`seam_utils.py` mit `compute_motion_scores`, `find_jumps`, `run_rife`,
  `ffprobe_*`), aktuell aber bewusst noch nicht gemacht.
- Getestet mit `rife-ncnn-vulkan` Release `20221029`, Modell `rife-v4.6`
  (großzügig für allgemeine Videos geeignet; `rife-v2.3` ist das Tool-Default,
  ältere/schwächere Modellversion).
