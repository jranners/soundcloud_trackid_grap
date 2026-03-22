# Run Report: `https://soundcloud.com/urem/urem-fusion-festival-2025-tanzwuste`

## Status

Run executed. Download stage succeeded, analysis stage failed.

## IDs

- `task_id`: `c75ebaa6-2b04-47c2-b4e0-a408361dd45b`
- `tracklist_id`: `46bfade5-e86c-4cc3-955e-a2aa1fa07f79`

## Stage Results

- ✅ Services started (`docker compose up --build -d`)
- ✅ `POST /analyze` returned IDs
- ✅ Download completed (reported: ~111.01 MiB in ~10s)
- ❌ `app.tasks.analysis.segment_audio` failed

## Error Snippet (worker-analysis)

```text
Analysis failed for 46bfade5-e86c-4cc3-955e-a2aa1fa07f79: 'increase' is not a parameter of SBic
ValueError("'increase' is not a parameter of SBic")
```

## Failure Classification

- **Component:** Essentia SBic parameterization
- **Type:** Library/API incompatibility
- **Likely root cause:** `SBic(...)` is called with `increase=...`, but the installed Essentia version does not support this parameter.
- **Effect:** Task retries, but each retry fails identically (deterministic failure).

## Recommended Fix Direction

1. Update `app/tasks/analysis.py` SBic initialization to match current Essentia API.
2. Keep fallback transition detection path intact.
3. Add/adjust tests for SBic constructor arguments compatibility.

## Useful Context for Escalation

If passing this to a stronger model, include:

- Current `SBic(...)` call from `app/tasks/analysis.py`
- Full traceback from `worker-analysis`
- Essentia package version inside container
- One successful download log line + failed analysis log line for same `tracklist_id`
