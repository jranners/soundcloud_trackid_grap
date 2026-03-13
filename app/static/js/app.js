/* ── Utility helpers ── */
function fmt(sec) {
  if (sec == null || isNaN(sec)) return '--:--';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/* ── DOM refs ── */
const urlInput      = document.getElementById('url-input');
const analyzeBtn    = document.getElementById('analyze-btn');
const errorMsg      = document.getElementById('error-msg');
const statusSection = document.getElementById('status-section');
const resultSection = document.getElementById('results-section');
const statusBanner  = document.getElementById('status-banner');
const statusTitle   = document.getElementById('status-title');
const statusDetail  = document.getElementById('status-detail');
const statusIconEl  = document.getElementById('status-icon');
const spinnerEl     = document.getElementById('spinner');
const progressFill  = document.getElementById('progress-fill');
const trackCount    = document.getElementById('track-count');
const trackList     = document.getElementById('track-list');
const sourceUrl     = document.getElementById('source-url');

let pollTimer = null;
let currentTaskId = null;
let currentTracklistId = null;

/* ── Submit handler ── */
analyzeBtn.addEventListener('click', startAnalysis);
urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') startAnalysis();
});

async function startAnalysis() {
  const url = urlInput.value.trim();
  if (!url) {
    showError('Please enter a SoundCloud URL.');
    return;
  }
  try {
    const parsed = new URL(url);
    if (parsed.hostname !== 'soundcloud.com' && !parsed.hostname.endsWith('.soundcloud.com')) {
      showError('Please enter a valid SoundCloud URL (e.g. https://soundcloud.com/…).');
      return;
    }
  } catch (_) {
    showError('Please enter a valid SoundCloud URL (e.g. https://soundcloud.com/…).');
    return;
  }

  hideError();
  setLoading(true);

  stopPolling();
  resultSection.style.display = 'none';

  try {
    const res = await fetch('/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Server error ${res.status}`);
    }

    const data = await res.json();
    currentTaskId = data.task_id;
    currentTracklistId = data.tracklist_id;

    showStatus('pending', 'Queued…', `Task: ${currentTaskId}`);
    startPolling();
  } catch (err) {
    setLoading(false);
    showError(err.message);
  }
}

/* ── Polling ── */
function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollStatus, 2500);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollStatus() {
  if (!currentTaskId) return;
  try {
    const res = await fetch(`/status/${currentTaskId}`);
    if (!res.ok) return;
    const data = await res.json();
    const status = (data.status || '').toLowerCase();

    if (status === 'pending') {
      showStatus('pending', 'Queued…', `Task: ${currentTaskId}`);
    } else if (status === 'started' || status === 'progress') {
      showStatus('started', 'Analyzing audio…', `Task: ${currentTaskId}`);
    } else if (status === 'success') {
      stopPolling();
      showStatus('success', 'Analysis complete!', `Task: ${currentTaskId}`);
      progressFill.classList.add('done');
      setLoading(false);
      await loadTracklist();
    } else if (status === 'failure') {
      stopPolling();
      setLoading(false);
      const detail = data.result?.exc_message || data.result || 'Unknown error';
      showStatus('error', 'Analysis failed', String(detail));
    } else {
      showStatus('started', `Status: ${status}`, `Task: ${currentTaskId}`);
    }
  } catch (_) {
    /* network hiccup – keep polling */
  }
}

/* ── Load results ── */
async function loadTracklist() {
  if (!currentTracklistId) return;
  try {
    const res = await fetch(`/tracklist/${currentTracklistId}`);
    if (!res.ok) return;
    const data = await res.json();
    renderResults(data);
  } catch (_) {
    /* silently ignore */
  }
}

/* ── Render ── */
function renderResults(data) {
  const tracks = data.tracks || [];
  trackCount.textContent = `${tracks.length} track${tracks.length !== 1 ? 's' : ''}`;

  if (sourceUrl) {
    sourceUrl.textContent = data.url || '';
    sourceUrl.href = data.url || '#';
  }

  trackList.innerHTML = '';

  if (tracks.length === 0) {
    trackList.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24"><path d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/></svg>
        <p>No tracks identified yet.</p>
      </div>`;
  } else {
    tracks.forEach((track, i) => {
      const title  = track.title  || 'Unknown Title';
      const artist = track.artist || null;
      const start  = fmt(track.timestamp_start);
      const end    = fmt(track.timestamp_end);

      const item = document.createElement('div');
      item.className = 'track-item';
      item.innerHTML = `
        <span class="track-num">${i + 1}</span>
        <div class="track-art">
          <svg viewBox="0 0 24 24"><path d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/></svg>
        </div>
        <div class="track-info">
          <div class="track-title">${escHtml(title)}</div>
          <div class="track-artist ${artist ? '' : 'unknown'}">${escHtml(artist || 'Unknown Artist')}</div>
        </div>
        <div class="track-time">
          <div class="time-start">${start}</div>
          <div class="time-end">→ ${end}</div>
        </div>`;
      trackList.appendChild(item);
    });
  }

  resultSection.style.display = 'block';
  resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ── UI helpers ── */
function showStatus(type, title, detail) {
  statusSection.style.display = 'block';

  statusBanner.className = `status-banner ${type}`;
  statusTitle.textContent = title;
  statusDetail.textContent = detail;

  const isRunning = type === 'pending' || type === 'started';
  spinnerEl.style.display  = isRunning ? 'block' : 'none';
  statusIconEl.style.display = isRunning ? 'none' : 'block';

  const icons = { success: '✅', error: '❌' };
  statusIconEl.textContent = icons[type] || '⏳';
}

function setLoading(loading) {
  analyzeBtn.disabled = loading;
  urlInput.disabled = loading;
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.style.display = 'block';
}

function hideError() {
  errorMsg.style.display = 'none';
}

function escHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
