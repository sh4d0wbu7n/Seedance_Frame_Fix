# Handover / Kontext für zukünftige Weiterentwicklung

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
