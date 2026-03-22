# System Memory & Context: SoundCloud TrackID Grabber

## Projektübersicht
Dieses Projekt ist ein Self-Hosted-Service, der SoundCloud-Mixes analysiert und automatisch eine Tracklist erstellt, indem er die Audioinhalte herunterlädt, musikalische Übergänge erkennt und diese über die Shazam-API identifiziert.

### Die Kern-Pipeline:
1. **Download**: `yt-dlp` lädt das Audio (bevorzugt direktes HTTP mit >320kbps) auf eine RAM-Disk. Worker-Queue: `download`.
2. **Analysis/Segmentierung**: Essentia sucht nach Übergängen (`SBic` Algorithmus primär, Fallback auf Beat-Tracker/Onset Detection). Bei gefundenen Übergängen wird 30 Sekunden später ein 12-Sekunden-Snippet als WAV extrahiert. Worker-Queue: `analysis`.
3. **Fingerprinting**: Asynchrone Anfragen an die Shazam-API via `shazamio`, um die extrahierten WAV-Snippets zu identifizieren. Worker-Queue: `fingerprint`.
4. **Aggregation & API**: Die Ergebnisse werden in einer PostgreSQL-Datenbank abgelegt. Die API ist mit FastAPI gebaut (inklusive Celery Task-Polling via Flower).

### Technologie-Stack
- **Backend:** FastAPI, Python 3.x, Pydantic, SQLAlchemy, Alembic (Migrationen).
- **Task Queue:** Celery mit Redis als Broker und Backend.
- **Audio-Processing:** Essentia (MonoLoader, SBic, MFCC, etc.), FFmpeg (Snippet-Extraktion), yt-dlp.
- **Infrastructure:** Docker & Docker Compose (inklusive explizitem Migrations-Container).

---

## Bekannte Probleme & Bottlenecks
1. **Essentia SBic Parameter-Bug**: Aktueller Bug laut Error Reports (`'increase' is not a parameter of SBic`). Der Aufruf `es.SBic(...)` in `app.tasks.analysis.segment_audio` scheint inkompatibel mit der installierten Essentia-Version im Docker-Container zu sein.
2. **Dateiverfügbarkeit auf der RAM-Disk**: In der Vergangenheit gab es `FileNotFoundError`-Probleme in der Worker-Kommunikation. Zwar gibt es Recovery-Routinen, aber verteilte I/O über shared Volumes kann weiterhin fehleranfällig sein (Race Conditions zwischen File-Delete und Retry-Logik).
3. **Audio-Erkennungslücken**: Wenn Shazam die Tracks nicht findet oder Essentia den Übergang falsch platziert, geht der TrackID verloren.

---

## Fahrplan für nächste Schritte (Next Level)

### 1. Robustheit & Fehlerbehebung (Kurzfristig)
- **Essentia-Fix:** Den `SBic` Aufruf in `app/tasks/analysis.py` korrigieren und absichern. Es sollte validiert werden, ob Parameter wie `inc1` vs `increase` in der genutzten Library-Version richtig übergeben werden.
- **Fehler-Kapselung:** Die Exceptions in der Celery-Pipeline so kapseln, dass bei API-Änderungen von externen Libraries (Shazam, Essentia, yt-dlp) strukturiertere Logs entstehen.

### 2. Layout & Workflow Überarbeitung (Mittelfristig)
- **Code-Struktur:** Das Projekt sollte in klarere Domain-Driven-Module aufgeteilt werden (z.B. Core-Processing, Infrastructure, API-Layer, Database-Layer). Die `tasks/`-Ordner sollten noch stärker von direkten externen Abhängigkeiten abstrahiert werden.
- **Testing:** Ergänzen von echten Unit-Tests, speziell für die Parsing- und Fallback-Algorithmen (mocked Audio), um bei Essentia-Updates Regressionen zu verhindern.

### 3. Feature-Weiterentwicklung (Langfristig)
- **Beatport Downloader Integration:** Geplante Verbindung zu einem externen Beatport-Downloader-Repository, um nicht nur Tracks zu erkennen, sondern auch direkt in hoher Qualität als Kauf/Download bereitzustellen.
- **KI/ML-Verbesserung:** Statt starrer Essentia-Heuristiken könnten fortschrittlichere Transition-Detektoren (basierend auf CNNs oder Audio-Embeddings) eine akkuratere Erkennung bieten.
- **UI & Realtime-Websockets:** Derzeit wird gepollt (`GET /status...`). Eine Umstellung auf WebSockets könnte die User Experience beim Warten auf die Analyse drastisch verbessern.

## Notizen für andere Agenten:
- Bearbeite das Projekt im Ordner `/app/`.
- Führe Migrationen mit Container aus: `docker-compose run --rm migrate`.
- Wenn Code läuft, stelle sicher, dass Docker aktiv ist. Da wir uns oft im lokalen Windows-System des Users befinden, Vorsicht mit absoluten Pfaden: halte dich an relative Pfade innerhalb des Docker-Kontextes, wann immer möglich.
