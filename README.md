# SoundCloud TrackID Grabber

A self-hosted service that automatically identifies every track in a SoundCloud mix by downloading the audio, detecting transitions, fingerprinting each segment via the Shazam API, and returning a timestamped tracklist.

---

## How It Works

```
POST /analyze  →  download_audio  →  segment_audio  →  identify_tracks  →  aggregate_results
                      (yt-dlp)        (Essentia SBIC)     (Shazamio)         (PostgreSQL)
```

1. **Download** — `yt-dlp` fetches the best-quality audio stream from the given SoundCloud URL and writes it to a RAM-disk.
2. **Segment** — Essentia's SBIC (Sequential Bayesian Information Criterion) detects musical transitions. If no transitions are found, a beat-tracker + onset-detection fallback is used.
3. **Fingerprint** — For each detected transition, a 12-second WAV snippet (starting 30 s after the transition) is sent to the Shazam API via `shazamio`.
4. **Aggregate** — Identified track metadata (title, artist, timestamp) is saved to PostgreSQL and the tracklist status is set to `completed`.

Each step is an independent Celery task running on a dedicated worker queue (`download`, `analysis`, `fingerprint`). Flower is included for real-time task monitoring.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Docker | ≥ 24 |
| Docker Compose | ≥ 2 |

No local Python installation required — everything runs inside Docker.

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/jranners/soundcloud_trackid_grap.git
cd soundcloud_trackid_grap

# 2. (Optional) Override Flower credentials
export FLOWER_USER=admin
export FLOWER_PASSWORD=changeme

# 3. Build and start all services
docker compose up --build -d

# 4. Check the API is healthy
curl http://localhost:8000/health
# → {"status":"ok"}
```

---

## API Reference

### `POST /analyze`

Start a new analysis job for a SoundCloud URL.

**Request body**
```json
{ "url": "https://soundcloud.com/artist/mix-title" }
```

**Response**
```json
{
  "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "tracklist_id": "d290f1ee-6c54-4b01-90e6-d701748f0851"
}
```

---

### `GET /status/{task_id}`

Poll the Celery task status.

**Response**
```json
{
  "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "SUCCESS",
  "result": { "tracklist_id": "...", "status": "completed", "tracks": [] }
}
```

`status` mirrors Celery's standard states: `PENDING`, `STARTED`, `SUCCESS`, `FAILURE`, `RETRY`.

---

### `GET /tracklist/{tracklist_id}`

Retrieve the final tracklist with all identified tracks.

**Response**
```json
{
  "id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "url": "https://soundcloud.com/artist/mix-title",
  "status": "completed",
  "created_at": "2024-01-15T12:00:00+00:00",
  "updated_at": "2024-01-15T12:05:00+00:00",
  "tracks": [
    {
      "id": "...",
      "title": "Track Name",
      "artist": "Artist Name",
      "timestamp_start": 42.0,
      "timestamp_end": null,
      "snippet_path": null,
      "raw_result": { ... },
      "created_at": "2024-01-15T12:04:30+00:00"
    }
  ]
}
```

---

## Services

| Service | URL | Description |
|---|---|---|
| API | http://localhost:8000 | FastAPI REST interface |
| Flower | http://localhost:5555 | Celery task monitor (admin/admin) |

Interactive API documentation (Swagger UI) is available at **http://localhost:8000/docs**.

---

## Configuration

Environment variables (override in `docker-compose.yml` or via a `.env` file):

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | Celery broker & result backend |
| `DATABASE_URL` | `postgresql://user:password@postgres:5432/trackid` | PostgreSQL DSN |
| `RAMDISK_PATH` | `/app/ramdisk` | Temporary audio storage (tmpfs) |
| `FLOWER_USER` | `admin` | Flower basic-auth username |
| `FLOWER_PASSWORD` | `admin` | Flower basic-auth password |

---

## Database Migrations

Alembic is used for schema management:

```bash
# Apply all migrations (run inside the api container)
docker compose exec api alembic upgrade head

# Generate a new migration after model changes
docker compose exec api alembic revision --autogenerate -m "describe change"
```

---

## Running Tests

```bash
# Install dependencies
pip install -r requirements.txt

# Run the full test suite
python -m pytest tests/ -v
```

All 21 tests run without any external services (Redis, PostgreSQL, Shazam) — heavy dependencies are fully mocked.

---

## Project Structure

```
.
├── app/
│   ├── main.py          # FastAPI application & endpoints
│   ├── models.py        # SQLAlchemy ORM models (Tracklist, Track)
│   ├── database.py      # SQLAlchemy session factory
│   ├── celery_app.py    # Celery app configuration & routing
│   ├── config.py        # Pydantic settings (env-based)
│   └── tasks/
│       ├── __init__.py  # aggregate_results task
│       ├── download.py  # download_audio task (yt-dlp)
│       ├── analysis.py  # segment_audio task (Essentia)
│       └── fingerprint.py # identify_tracks task (Shazamio)
├── alembic/             # Database migration scripts
├── tests/               # Pytest test suite
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Stopping the Services

```bash
docker compose down          # Stop containers, keep volumes
docker compose down -v       # Stop containers and delete all data
```
