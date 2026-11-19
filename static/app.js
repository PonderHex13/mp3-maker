const jobsContainer = document.getElementById("jobsContainer");
const submitBtn = document.getElementById("submitBtn");
const submitInfo = document.getElementById("submitInfo");
const entriesInput = document.getElementById("entries");
const jobsInfo = document.getElementById("jobsInfo");

const REFRESH_MS = 3000;
const IDLE_REFRESH_MS = 30000;
let isRefreshing = false;
let refreshPending = false;
let refreshTimer = null;
let hasActiveJobs = true;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function toLines(text) {
  const raw = text.trim();
  if (!raw) return [];

  return raw
    .split(/\r?\n/)
    .flatMap((line) => {
      const trimmed = line.trim();
      // Split quoted groups only when they make up the entire line.
      if (/^(?:"[^"]+"\s*)+$/.test(trimmed)) {
        return Array.from(trimmed.matchAll(/"([^"]+)"/g), (match) => match[1].trim());
      }
      return [trimmed];
    })
    .filter((line) => line.length > 0);
}

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || "Invalid input").join("; ")
      : detail || `${response.status} ${response.statusText}`;
    throw new Error(message);
  }

  return body;
}

function badge(status) {
  const cls = escapeHtml(status || "queued");
  const label = escapeHtml(status || "queued");
  return `<span class="badge ${cls}">${label}</span>`;
}

function prettyFileName(pathValue) {
  if (!pathValue) return "";
  const base = String(pathValue).split(/[\\/]/).pop() || String(pathValue);
  // Normalize odd slash characters and decode URL-safe text if present.
  return base
    .replaceAll("⧸", "/")
    .replaceAll("﹨", "\\")
    .replaceAll("%20", " ");
}

function fileItem(jobId, item) {
  const status = item.status || "unknown";
  const path = item.path;
  const url = path && status === "ok"
    ? `/jobs/${encodeURIComponent(jobId)}/files/${item.entry_index}/download`
    : null;
  const displayFile = prettyFileName(path || item.deleted_path || "");
  const statusText = item.error || (displayFile ? `FILE: ${displayFile}` : "");

  return `
    <div class="file-item">
      <div class="file-main">
        <div class="file-left">
          <div class="entry-text">#${item.entry_index}: ${escapeHtml(item.input || "")}</div>
          <div class="file-name">${escapeHtml(statusText)}</div>
        </div>
        <div class="file-right">
          ${badge(status)}
          <div class="file-actions file-actions-right">
            ${url ? `<a href="${url}" download class="button secondary btn-download">Download</a>` : ""}
            ${status === "ok" ? `<button type="button" class="danger icon-delete" title="Delete Song" aria-label="Delete Song" data-delete-file="${jobId}:${item.entry_index}">&times;</button>` : status === "deleted" ? `<button type="button" class="secondary icon-delete" disabled>&times;</button>` : ""}
          </div>
        </div>
      </div>
    </div>
  `;
}

function jobCard(job) {
  const files = job.entries;
  const filesHtml = (files && files.length)
    ? files.map((item) => fileItem(job.job_id, item)).join("")
    : `<div class="empty">No files yet.</div>`;

  const actions = `
    <div class="file-actions">
      ${job.status === "done" ? `<a href="/jobs/${encodeURIComponent(job.job_id)}/download-all" class="button secondary">Download All</a>` : ""}
      <button type="button" class="danger" data-delete-job="${escapeHtml(job.job_id)}" ${job.status === "processing" ? 'disabled title="Wait for processing to finish"' : ""}>Clear Job</button>
    </div>
  `;

  return `
    <article class="job-card">
      <div class="job-row">
        ${badge(job.status)}
        <strong>${escapeHtml(job.job_id)}</strong>
      </div>
      ${actions}
      <div class="file-list">${filesHtml}</div>
      <div class="muted">${job.error ? escapeHtml(job.error) : ""}</div>
    </article>
  `;
}

async function submitJob() {
  const entries = toLines(entriesInput.value);
  if (!entries.length) {
    submitInfo.textContent = "Please add at least one line.";
    return;
  }

  submitBtn.disabled = true;
  submitInfo.textContent = "Submitting...";
  try {
    const result = await apiFetch("/enqueue", {
      method: "POST",
      body: JSON.stringify({ entries }),
    });
    submitInfo.textContent = `Submitted job: ${result.job_id}`;
    entriesInput.value = "";
    await refreshJobs();
  } catch (err) {
    submitInfo.textContent = `Error: ${err.message}`;
  } finally {
    submitBtn.disabled = false;
  }
}

async function deleteJob(jobId) {
  try {
    await apiFetch(`/jobs/${jobId}`, { method: "DELETE" });
    await refreshJobs();
  } catch (err) {
    alert(`Delete job failed: ${err.message}`);
  }
}

async function deleteJobFile(jobId, entryIndex) {
  try {
    await apiFetch(`/jobs/${jobId}/files/${entryIndex}`, { method: "DELETE" });
    await refreshJobs();
  } catch (err) {
    alert(`Delete song failed: ${err.message}`);
  }
}

async function refreshJobs() {
  if (isRefreshing) {
    refreshPending = true;
    return;
  }
  isRefreshing = true;
  clearTimeout(refreshTimer);

  try {
    const list = await apiFetch("/jobs");
    const jobs = list.jobs || [];
    hasActiveJobs = jobs.some((job) => job.status === "queued" || job.status === "processing");
    jobsInfo.textContent = hasActiveJobs ? "Checking active jobs every 3s" : "Checking for updates every 30s";

    if (!jobs.length) {
      jobsContainer.innerHTML = `<div class="empty">No jobs yet. Submit entries above.</div>`;
      return;
    }

    jobsContainer.innerHTML = jobs.map((job) => jobCard(job)).join("");

    jobsContainer.querySelectorAll("[data-delete-job]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const jobId = btn.getAttribute("data-delete-job");
        if (jobId) deleteJob(jobId);
      });
    });

    jobsContainer.querySelectorAll("[data-delete-file]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-delete-file");
        if (!key) return;
        const [jobId, idx] = key.split(":");
        deleteJobFile(jobId, Number(idx));
      });
    });
  } catch (err) {
    jobsInfo.textContent = `Could not refresh jobs: ${err.message}`;
  } finally {
    isRefreshing = false;
    if (refreshPending) {
      refreshPending = false;
      refreshJobs();
    } else if (!document.hidden) {
      refreshTimer = setTimeout(refreshJobs, hasActiveJobs ? REFRESH_MS : IDLE_REFRESH_MS);
    }
  }
}

submitBtn.addEventListener("click", submitJob);
document.addEventListener("visibilitychange", () => {
  clearTimeout(refreshTimer);
  if (!document.hidden) refreshJobs();
});
refreshJobs();
