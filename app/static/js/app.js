function fmt(sec) {
  if (sec == null || Number.isNaN(Number(sec))) return "--:--";
  const m = Math.floor(Number(sec) / 60);
  const s = Math.floor(Number(sec) % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatConfidencePct(value) {
  const num = Number(value ?? 0);
  if (!Number.isFinite(num)) return "0%";
  const pct = Math.max(0, Math.min(100, Math.round(num * 100)));
  return `${pct}%`;
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
      <div id="bp-container-${escHtml(job.tracklistId)}" style="margin-top:1rem;">
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
          <button
            class="btn btn-secondary tracklist-toggle"
            type="button"
            data-tracklist-id="${escHtml(job.tracklistId)}"
          >
            ${isExpanded ? "Trackliste zuklappen" : "Trackliste aufklappen"}
          </button>
          <button
            class="btn btn-primary beatport-dl-btn"
            type="button"
            data-mode="zip"
            data-tracklist-id="${escHtml(job.tracklistId)}"
          >
            BeatportDL (Als ZIP)
          </button>
          <button
            class="btn btn-primary beatport-dl-btn"
            type="button"
            data-mode="server"
            data-tracklist-id="${escHtml(job.tracklistId)}"
          >
            BeatportDL (Auf Server)
          </button>
        </div>
      </div>` : ""}

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
    const confidence = Number(track.confidence_score ?? 0);
    const lowConfidence = confidence < 0.6;
    const confidenceClass = lowConfidence ? "low" : confidence < 0.8 ? "mid" : "high";
    const confidenceLabel = formatConfidencePct(confidence);
    const snippetsInfo = `${Number(track.num_consistent_snippets ?? 0)}/${Number(track.num_snippets ?? 0)} snippets`;
    
    let linkHtml = "";
    if (track.raw_result && track.raw_result.track) {
      const tr = track.raw_result.track;
      const url = tr.apple_music_url || tr.url || "";
      if (url) {
        linkHtml = `<a href="${escHtml(url)}" target="_blank" class="track-link" title="Listen on Apple Music / Shazam" style="margin-left: auto; margin-right: 15px; font-size: 1.25rem; text-decoration: none; align-self: center;">🎵</a>`;
      }
    }

    return `
      <div class="track-item">
         <div class="track-item-header">
           <div class="track-num">#${i + 1}</div>
           <div class="track-time">
              <div class="time-main">${start}</div>
              <div class="time-sub">Start time</div>
           </div>
         </div>
         <div class="track-item-body">
           <div class="track-art">
             <svg viewBox="0 0 24 24"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
           </div>
           <div class="track-info">
             <div class="track-title">${title}</div>
             <div class="track-artist ${unknown}">${artist}</div>
            </div>
          </div>
          <div class="track-confidence ${confidenceClass}">
            <span class="confidence-value">${confidenceLabel}</span>
            <span class="confidence-meta">${snippetsInfo}</span>
            ${lowConfidence ? '<span class="confidence-warning">Unsicher</span>' : ''}
          </div>
          ${linkHtml ? `<div style="display:flex; justify-content:flex-end; width:100%; border-top:1px solid rgba(255,255,255,0.05); padding-top:10px;">${linkHtml}</div>` : ''}
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

let beatportApiUrl = "http://192.168.178.39:10091";
fetch("/config").then(r => r.json()).then(d => {
  if(d.beatportdl_api_url) beatportApiUrl = d.beatportdl_api_url.replace(/\/$/, "");
}).catch(()=>{});

jobsList?.addEventListener("click", async (event) => {
  const beatportBtn = event.target.closest(".beatport-dl-btn");
  if (beatportBtn) {
    const tracklistId = beatportBtn.getAttribute("data-tracklist-id");
    const mode = beatportBtn.getAttribute("data-mode") || "zip";
    if (!tracklistId) return;
    
    const container = document.getElementById(`bp-container-${tracklistId}`);
    if(container) {
       container.innerHTML = `
         <div class="status-banner pending">
            <div class="spinner" style="display:block"></div>
            <div class="status-info">
              <div class="status-title">Suchlauf auf Beatport läuft...</div>
              <div class="status-detail">Tracks werden im Hintergrund gesucht</div>
            </div>
         </div>
       `;
    }
    
    try {
      const res = await fetch(`/beatport/send-all/${encodeURIComponent(tracklistId)}?mode=${encodeURIComponent(mode)}`, { method: "POST" });
      if (!res.ok) throw new Error("Fehler beim Senden");
      const data = await res.json();
      
      // Poll celery job
      const pollCelery = setInterval(async () => {
         try {
           const stRes = await fetch(`/status/${data.task_id}?tracklist_id=${encodeURIComponent(tracklistId)}`);
           if(!stRes.ok) return;
           const stData = await stRes.json();
           const st = String(stData.status||"").toUpperCase();
           if(st === "SUCCESS") {
              clearInterval(pollCelery);
              const bpJobId = stData.result?.beatport_job_id;
              if(!bpJobId) {
                 if(container) container.innerHTML = `<div class="status-banner error"><div class="status-info"><div class="status-title">Fehler</div><div class="status-detail">Keine Tracks gefunden oder Job ID fehlt.</div></div></div>`;
                 return;
              }
              startBeatportSSE(container, bpJobId, mode);
           } else if (st === "FAILURE") {
              clearInterval(pollCelery);
              if(container) container.innerHTML = `<div class="status-banner error"><div class="status-info"><div class="status-title">Fehler</div><div class="status-detail">Suche fehlgeschlagen.</div></div></div>`;
           }
         } catch(e){}
      }, 1500);
      
    } catch (_) {
      if(container) container.innerHTML = `<div class="status-banner error"><div class="status-info"><div class="status-title">Fehler</div><div class="status-detail">Konnte nicht gestartet werden.</div></div></div>`;
    }
    return;
  }

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

function startBeatportSSE(container, jobId, mode) {
  if(!container) return;
  
  // Render initial progress bar
  container.innerHTML = `
    <div class="status-banner started">
      <div class="spinner" style="display:block"></div>
      <div class="status-info">
        <div class="status-title" id="bp-title-${jobId}">Download startet...</div>
        <div class="status-detail" id="bp-detail-${jobId}">Verbinde mit BeatportDL...</div>
      </div>
    </div>
    <div class="progress-bar-wrap">
      <div class="progress-bar-fill" id="bp-bar-${jobId}" style="width:0%"></div>
    </div>
  `;
  
  const titleEl = document.getElementById(`bp-title-${jobId}`);
  const detailEl = document.getElementById(`bp-detail-${jobId}`);
  const barEl = document.getElementById(`bp-bar-${jobId}`);
  
  const sse = new EventSource(`${beatportApiUrl}/api/download/status/stream`);
  
  sse.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if(data.type === "progress" && data.jobId === jobId) {
         if(titleEl) titleEl.textContent = "Lade von Beatport herunter...";
         if(detailEl) detailEl.textContent = data.progress?.stage || "Wird heruntergeladen...";
         if(barEl) {
            barEl.style.width = Math.max(5, (data.progress?.value || 0)) + "%";
            barEl.classList.remove("done");
         }
      } else if(data.type === "completed" && data.jobId === jobId) {
         if(titleEl) titleEl.textContent = "Download Abgeschlossen!";
         if(detailEl) detailEl.textContent = "Alle Tracks wurden erfolgreich geladen.";
         if(barEl) {
            barEl.style.width = "100%";
            barEl.classList.add("done");
         }
         container.querySelector(".status-banner").className = "status-banner success";
         container.querySelector(".spinner").style.display = "none";
         
         if(mode === "zip" && data.file) {
            window.location.href = `${beatportApiUrl}/api/download/file/${data.file}`;
         }
         sse.close();
      } else if(data.type === "failed" && data.jobId === jobId) {
         if(titleEl) titleEl.textContent = "Fehler beim Download";
         if(detailEl) detailEl.textContent = data.error || "Unbekannter Fehler";
         container.querySelector(".status-banner").className = "status-banner error";
         container.querySelector(".spinner").style.display = "none";
         sse.close();
      }
    } catch(err){}
  };
  
  sse.onerror = () => {
     sse.close();
  };
}
