# Failure Analysis Summary (SoundCloud TrackID Grabber)

## Scope

This document summarizes recurring production failures observed while analyzing SoundCloud sets, including root causes, evidence, mitigations already applied, and what to capture for escalation to a stronger model.

## Observed Failures

### 1) `UndefinedTable: relation "tracklists" does not exist`

**Symptom**
- API `POST /analyze` fails immediately on DB insert.

**Cause**
- Schema migrations were not guaranteed to run before API/worker startup.

**Fix Applied**
- Added dedicated `migrate` compose service (`alembic upgrade head`).
- API/workers now depend on successful migration completion.

---

### 2) `RuntimeError ... Could not open file "/app/ramdisk/<id>.m4a"`

**Symptom**
- `app.tasks.analysis.segment_audio` fails at `Essentia MonoLoader`.
- Error appears after download task reported success.

**Primary Causes (combined)**
1. Cross-worker file visibility mismatch risk in earlier setup.
2. Retry flow removed/expected audio file at wrong time in analysis logic.
3. Path staleness race: saved path may not exist when analysis starts.

**Fixes Applied**
- Switched workers to shared volume at `/app/ramdisk`.
- Adjusted analysis cleanup so source audio is removed only after successful segmentation or final failure.
- Added defensive recovery in `segment_audio`: if given `audio_path` is missing, re-scan `/app/ramdisk/<tracklist_id>.*`.

---

### 3) UI error text shown as `[object Object]`

**Symptom**
- Failed jobs displayed unreadable error message.

**Cause**
- Client rendered non-string error payloads directly.

**Fix Applied**
- Added structured `formatErrorDetail()` in UI (supports `exc_message`, `message`, JSON fallback, `{}` -> `Unknown error`).

---

### 4) Failed jobs remained visible

**Symptom**
- User requested failed jobs to disappear, but stale failed cards persisted.

**Fix Applied**
- Frontend removes failed jobs immediately on polling failure state.
- `/jobs` endpoint now prunes failed rows and supports status filters (`active`, `completed`, `all`).

---

### 5) Download much slower than expected

**Symptom**
- Download took minutes instead of expected seconds on high bandwidth.

**Likely Causes**
- Prior artificial delay (`sleep_requests`) throttled requests.
- SoundCloud often serves fragmented HLS; throughput can be lower than direct HTTP media.
- Format selection may not prioritize fastest high-bitrate direct stream.

**Fixes Applied**
- Removed request sleep throttle.
- Updated yt-dlp format preference to prioritize high-bitrate direct HTTP first:
  `bestaudio[abr>=320][protocol^=http] / bestaudio[protocol^=http] / bestaudio / best`
- Increased fragment concurrency and retries for robustness.

**Important Reality Check**
- “320kbps in ~3s for 100MB” is physically inconsistent: 320 kbps equals ~40 KB/s (too slow for 100MB in seconds).  
  If source provides higher bitrate or direct file transfer, real speed can still be much faster than HLS, but depends on SoundCloud CDN behavior and selected format.

## Added UX/Feature Behavior

- Reload-safe jobs via persisted DB metadata and `/jobs`.
- Tabs in UI:
  - `Aktiv` = running/queued analyses
  - `Fertig` = completed analyses with tracklists
- Early metadata hydration (title/cover) using prefetch during `/analyze`.

## What to Provide on Next Failure (Escalation Pack)

1. Exact task traceback from Flower (full stack trace).
2. Output of:
   - `docker compose logs worker-download --tail=200`
   - `docker compose logs worker-analysis --tail=200`
   - `docker compose logs api --tail=200`
3. One failing `tracklist_id` and `task_id`.
4. Result of checking shared files in worker-analysis container:
   - `ls -lah /app/ramdisk | grep <tracklist_id>`
5. `/status/{task_id}?tracklist_id=...` payload at failure time.
6. `/jobs?status=active` and `/jobs?status=completed` payload samples.

## Current Hypothesis if Failures Persist

If `No such file` still occurs after shared-volume + recovery logic, strongest candidates are:
- download result path mismatch due to extension churn and race timing,
- cleanup executed by unexpected retry interleaving,
- container-level mount inconsistency in a stale deployment (old containers not recreated).

In that case, force full recreate:

```bash
docker compose down -v
docker compose up --build -d
```

