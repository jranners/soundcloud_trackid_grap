function fmt(sec) {
  if (sec == null || Number.isNaN(Number(sec))) return "--:--";
  const m = Math.floor(Number(sec) / 60);
  const s = Math.floor(Number(sec) % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function escHtml(value) {
  const str = String(value ?? "");
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

const urlInput = document.getElementById("url-input");
const analyzeBtn = document.getElementById("analyze-btn");
const errorMsg = document.getElementById("error-msg");
const jobsList = document.getElementById("jobs-list");
const jobCount = document.getElementById("job-count");
const setSearchInput = document.getElementById("set-search-input");
const tabActiveBtn = document.getElementById("tab-active");
const tabCompletedBtn = document.getElementById("tab-completed");

const jobs = new Map();
const expandedTracklists = new Set();
let pollTimer = null;
let currentTab = "active";

analyzeBtn.addEventListener("click", startAnalysis);
urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") startAnalysis();
});
tabActiveBtn?.addEventListener("click", () => switchTab("active"));
tabCompletedBtn?.addEventListener("click", () => switchTab("completed"));
setSearchInput?.addEventListener("input", renderJobs);

initJobs();

async function initJobs() {
  try {
    const res = await fetch(`/jobs?limit=50&status=${encodeURIComponent(currentTab)}`);
    if (!res.ok) {
      renderJobs();
      return;
    }
    const data = await res.json();
    const list = Array.isArray(data.jobs) ? data.jobs : [];
    jobs.clear();
    for (const item of list) {
      const progress = item.progress || {};
      jobs.set(item.task_id || item.id, {
        taskId: item.task_id || "",
        tracklistId: item.id,
        url: item.url || "",
        setTitle: item.set_title || "",
        coverUrl: item.cover_url || "",
        status: String(item.status || "PENDING").toUpperCase(),
        progress: Number(progress.progress ?? 0),
        stageTitle: progress.title || "Queued",
        detail: progress.message || (item.task_id ? `Task: ${item.task_id}` : "Queued"),
        processedSegments: progress.processed_segments ?? null,
        totalSegments: progress.total_segments ?? null,
        tracks: null,
      });
    }
    renderJobs();
    if (currentTab === "active") {
      startPolling();
    }
    await Promise.all(
      [...jobs.values()]
        .filter((j) => j.status === "SUCCESS" || j.status === "COMPLETED")
        .map(loadTracklist)
    );
    renderJobs();
  } catch (_) {
    renderJobs();
  }
}

function switchTab(tab) {
  if (tab !== "active" && tab !== "completed") return;
  currentTab = tab;
  jobs.clear();
  expandedTracklists.clear();
  if (tab === "active") {
    tabActiveBtn?.classList.add("active");
    tabCompletedBtn?.classList.remove("active");
    startPolling();
  } else {
    tabCompletedBtn?.classList.add("active");
    tabActiveBtn?.classList.remove("active");
    stopPolling();
  }
  initJobs();
}

async function startAnalysis() {
  const url = urlInput.value.trim();
  if (!url) {
    showError("Bitte eine SoundCloud-URL eingeben.");
    return;
  }
  try {
    const parsed = new URL(url);
    if (parsed.hostname !== "soundcloud.com" && !parsed.hostname.endsWith(".soundcloud.com")) {
      showError("Bitte eine gültige SoundCloud-URL eingeben.");
      return;
    }
  } catch (_) {
    showError("Bitte eine gültige SoundCloud-URL eingeben.");
    return;
  }

  hideError();
  analyzeBtn.disabled = true;

  try {
    const res = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Serverfehler ${res.status}`);
    }

    const data = await res.json();
    jobs.set(data.task_id, {
      taskId: data.task_id,
      tracklistId: data.tracklist_id,
      url,
      setTitle: "",
      coverUrl: "",
      status: "PENDING",
      progress: 5,
      stageTitle: "Queued",
      detail: `Task: ${data.task_id}`,
      processedSegments: 0,
      totalSegments: null,
      tracks: null,
    });
    renderJobs();
    switchTab("active");
    urlInput.value = "";
  } catch (err) {
    showError(err.message);
  } finally {
    analyzeBtn.disabled = false;
  }
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(pollJobs, 2500);
}

function stopPolling() {
  if (!pollTimer) return;
  clearInterval(pollTimer);
  pollTimer = null;
}

async function pollJobs() {
  if (currentTab !== "active") {
    stopPolling();
    return;
  }
  const active = [...jobs.values()].filter((j) => j.taskId && !["SUCCESS", "FAILURE"].includes(j.status));
  if (active.length === 0) {
    stopPolling();
    return;
  }

  await Promise.all(active.map(pollSingleJob));
  renderJobs();
}

async function pollSingleJob(job) {
  try {
    const res = await fetch(`/status/${job.taskId}?tracklist_id=${encodeURIComponent(job.tracklistId)}`);
    if (!res.ok) return;
    const data = await res.json();
    const status = String(data.status || "").toUpperCase();
    job.status = status;

    const progress = data.progress || null;
    if (progress) {
      job.progress = Number(progress.progress ?? job.progress);
      job.stageTitle = progress.title || job.stageTitle;
      job.detail = progress.message || job.detail;
      job.processedSegments = progress.processed_segments ?? job.processedSegments;
      job.totalSegments = progress.total_segments ?? job.totalSegments;
    } else if (status === "PENDING") {
      job.progress = 5;
      job.stageTitle = "Queued";
    } else if (status === "STARTED") {
      job.progress = Math.max(job.progress, 10);
      job.stageTitle = "Running";
    }

    if (status === "SUCCESS") {
      job.progress = 100;
      job.stageTitle = "Completed";
      await loadTracklist(job);
    }
    if (status === "FAILURE") {
      const detail = formatErrorDetail(data.result);
      showError(`Analyse fehlgeschlagen: ${detail}`);
      jobs.delete(job.taskId || job.tracklistId);
      return;
    } else {
      if (!job.detail) {
        job.detail = `Task: ${job.taskId}`;
      }
    }

    const tr = data.tracklist || {};
    if (tr.set_title) job.setTitle = tr.set_title;
    if (tr.cover_url) job.coverUrl = tr.cover_url;
    if (tr.url) job.url = tr.url;
  } catch (_) {
    // keep polling on transient errors
  }
}

async function loadTracklist(job) {
  if (job.tracks) return;
  try {
    const res = await fetch(`/tracklist/${job.tracklistId}`);
    if (!res.ok) return;
    const data = await res.json();
    job.url = data.url || job.url;
    job.setTitle = data.set_title || job.setTitle;
    job.coverUrl = data.cover_url || job.coverUrl;
    job.tracks = data.tracks || [];
  } catch (_) {
    // keep UI responsive
  }
}

function renderJobs() {
  const query = (setSearchInput?.value || "").trim().toLowerCase();
  const allItems = [...jobs.values()].sort((a, b) => a.taskId < b.taskId ? 1 : -1);
  const items = allItems.filter((job) => matchesFilter(job, query));
  if (currentTab === "active") {
    const activeCount = items.filter((j) => !["SUCCESS", "FAILURE"].includes(j.status)).length;
    jobCount.textContent = `${activeCount} aktiv`;
  } else {
    jobCount.textContent = `${items.length} fertig`;
  }

  if (items.length === 0) {
    jobsList.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24"><path d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/></svg>
        <p>Noch keine Analysen gestartet.</p>
      </div>`;
    return;
  }

  jobsList.innerHTML = items.map(renderJobCard).join("");
}

function renderJobCard(job) {
  const stateClass = toStateClass(job.status);
  const isRunning = stateClass === "pending" || stateClass === "started";
  const safeUrl = escHtml(job.url || "");
  const safeSetTitle = escHtml(job.setTitle || "SoundCloud Set");
  const safeTitle = escHtml(job.stageTitle || "Running");
  const safeDetail = escHtml(job.detail || "");
  const progress = Math.max(0, Math.min(100, Number(job.progress || 0)));
  const tracks = job.tracks;
  const canOpenTracklist = String(job.status || "").toUpperCase() === "SUCCESS" || String(job.status || "").toUpperCase() === "COMPLETED";
  const isExpanded = expandedTracklists.has(job.tracklistId);
  const tracksHtml = Array.isArray(tracks) ? renderTracks(tracks, isExpanded) : "";
  const countText = Array.isArray(tracks) ? `${tracks.length} track${tracks.length === 1 ? "" : "s"}` : "";

  const taskLabel = escHtml(job.taskId || job.tracklistId);
  return `
    <article class="card job-card">
      <div class="job-top">
        <div class="job-meta">
          <span class="badge">Task</span>
          <span class="job-id">${taskLabel}</span>
        </div>
        ${countText ? `<span class="badge">${countText}</span>` : ""}
      </div>

      <div class="set-header">
        ${job.coverUrl ? `<img class="set-cover" src="${escHtml(job.coverUrl)}" alt="Set cover" loading="lazy" />` : `<div class="set-cover placeholder"></div>`}
        <div class="set-title-wrap">
          <div class="set-title">${safeSetTitle}</div>
          <div class="set-subtitle">${safeUrl || "Unknown URL"}</div>
        </div>
      </div>

      <div class="status-banner ${stateClass}">
        <div class="spinner" style="display:${isRunning ? "block" : "none"}"></div>
        <span class="status-icon" style="display:${isRunning ? "none" : "block"}">${stateClass === "success" ? "✅" : stateClass === "error" ? "❌" : "⏳"}</span>
        <div class="status-info">
          <div class="status-title">${safeTitle}</div>
          <div class="status-detail">${safeDetail}</div>
        </div>
      </div>

      <div class="progress-bar-wrap">
        <div class="progress-bar-fill ${progress === 100 ? "done" : ""}" style="width:${progress}%"></div>
      </div>

      <div class="progress-meta">
        <span>${progress}%</span>
        <span>${formatSegmentProgress(job.processedSegments, job.totalSegments)}</span>
      </div>

      <div class="source-meta">
        <span>Source:</span>
        <a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a>
      </div>

      ${canOpenTracklist ? `
      <button
        class="btn btn-secondary tracklist-toggle"
        type="button"
        data-tracklist-id="${escHtml(job.tracklistId)}"
      >
        ${isExpanded ? "Trackliste zuklappen" : "Trackliste aufklappen"}
      </button>` : ""}

      ${tracksHtml}
    </article>
  `;
}

function renderTracks(tracks, expanded) {
  const cls = expanded ? "track-list" : "track-list collapsed";
  if (tracks.length === 0) {
    return `
      <div class="${cls}">
        <div class="empty-state"><p>No tracks identified.</p></div>
      </div>
    `;
  }

  const rows = tracks.map((track, i) => {
    const title = escHtml(track.title || "Unknown Title");
    const artist = escHtml(track.artist || "Unknown Artist");
    const start = fmt(track.timestamp_start);
    const end = fmt(track.timestamp_end);
    const unknown = track.artist ? "" : "unknown";
    return `
      <div class="track-item">
        <span class="track-num">${i + 1}</span>
        <div class="track-art">
          <svg viewBox="0 0 24 24"><path d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/></svg>
        </div>
        <div class="track-info">
          <div class="track-title">${title}</div>
          <div class="track-artist ${unknown}">${artist}</div>
        </div>
        <div class="track-time">
          <div class="time-start">${start}</div>
          <div class="time-end">→ ${end}</div>
        </div>
      </div>
    `;
  }).join("");

  return `<div class="${cls}">${rows}</div>`;
}

function toStateClass(status) {
  const upper = String(status || "").toUpperCase();
  if (upper === "SUCCESS" || upper === "COMPLETED") return "success";
  if (upper === "FAILURE") return "error";
  if (upper === "PENDING") return "pending";
  return "started";
}

function formatSegmentProgress(processed, total) {
  if (processed == null && total == null) return "Segmente: n/a";
  if (total == null) return `Segmente verarbeitet: ${processed ?? 0}`;
  return `Segmente: ${processed ?? 0}/${total}`;
}

function formatErrorDetail(result) {
  if (result == null) return "Unknown error";
  if (typeof result === "string") return result;
  if (typeof result === "number" || typeof result === "boolean") return String(result);
  if (typeof result === "object") {
    if (typeof result.exc_message === "string") return result.exc_message;
    if (typeof result.message === "string") return result.message;
    try {
      const text = JSON.stringify(result);
      return text === "{}" ? "Unknown error" : text;
    } catch (_) {
      return "Unknown error";
    }
  }
  return "Unknown error";
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.style.display = "block";
}

function hideError() {
  errorMsg.style.display = "none";
}

function matchesFilter(job, query) {
  if (!query) return true;
  const haystack = [
    job.setTitle,
    job.url,
    job.taskId,
    job.tracklistId,
    job.detail,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

jobsList?.addEventListener("click", (event) => {
  const button = event.target.closest(".tracklist-toggle");
  if (!button) return;
  const tracklistId = button.getAttribute("data-tracklist-id");
  if (!tracklistId) return;
  const job = [...jobs.values()].find((j) => j.tracklistId === tracklistId);
  if (!job) return;
  if (expandedTracklists.has(tracklistId)) {
    expandedTracklists.delete(tracklistId);
    renderJobs();
  } else {
    expandedTracklists.add(tracklistId);
    if (!Array.isArray(job.tracks)) {
      loadTracklist(job).finally(() => renderJobs());
      return;
    }
    renderJobs();
  }
});

window.setInterval(async () => {
  if (currentTab !== "active") return;
  try {
    const res = await fetch("/jobs?limit=50&status=active");
    if (!res.ok) return;
    const data = await res.json();
    const list = Array.isArray(data.jobs) ? data.jobs : [];
    const serverIds = new Set(list.map((j) => j.task_id || j.id));
    for (const key of [...jobs.keys()]) {
      if (!serverIds.has(key)) {
        jobs.delete(key);
      }
    }
    renderJobs();
  } catch (_) {
    // ignore background refresh errors
  }
}, 10000);
