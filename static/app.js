const jobsContainer = document.getElementById("jobsContainer");
const submitBtn = document.getElementById("submitBtn");
const submitInfo = document.getElementById("submitInfo");
const entriesInput = document.getElementById("entries");
const jobsInfo = document.getElementById("jobsInfo");
const entryCount = document.getElementById("entryCount");
const refreshBtn = document.getElementById("refreshBtn");
const clearHistoryBtn = document.getElementById("clearHistoryBtn");
const historyInfo = document.getElementById("historyInfo");
const clearHistoryDialog = document.getElementById("clearHistoryDialog");
const clearHistoryMessage = document.getElementById("clearHistoryMessage");

const REFRESH_MS = 3000;
const IDLE_REFRESH_MS = 30000;
let isRefreshing = false;
let refreshPending = false;
let refreshTimer = null;
let hasActiveJobs = true;
let currentJobs = [];
let isClearingHistory = false;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function cleanError(value) {
  return String(value ?? "").replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "");
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
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  return body;
}

function badge(status, text = status) {
  const cls = escapeHtml(status || "queued");
  const label = escapeHtml(text || "queued");
  return `<span class="badge ${cls}">${label}</span>`;
}

function prettyFileName(pathValue) {
  if (!pathValue) return "";
  const base = String(pathValue).split(/[\\/]/).pop() || String(pathValue);
  // Normalize odd slash characters and decode URL-safe text if present.
  return base
    .replace(/ \[[0-9a-f]{32}\](?=\.mp3$)/i, "")
    .replaceAll("⧸", "/")
    .replaceAll("﹨", "\\")
    .replaceAll("%20", " ");
}

function fileItem(jobId, item, jobStatus) {
  const status = item.status || "unknown";
  const path = item.path;
  const url = path && status === "ok"
    ? `/jobs/${encodeURIComponent(jobId)}/files/${item.entry_index}/download`
    : null;
  const displayFile = prettyFileName(path || item.deleted_path || "");
  const input = item.input || "";
  const isUrl = /^https?:\/\//i.test(input);
  const title = displayFile ? displayFile.replace(/\.mp3$/i, "") : (isUrl ? "Song from link" : input || "Song");
  const nextStep = item.error && /only individual spotify track links/i.test(item.error)
    ? "Use a Spotify track link, or enter the artist and song title."
    : "";

  return `
    <div class="file-item">
      <div class="file-main">
        ${badge(status, ({ ok: "Ready", error: "Failed", processing: "Processing", queued: "Queued", deleted: "Deleted" })[status] || status)}
        <div class="file-left">
          <div class="file-name">${escapeHtml(title)}</div>
          ${input && (isUrl || (displayFile && input !== title)) ? `<div class="entry-text">${isUrl ? "Source" : "Requested"}: ${escapeHtml(input)}</div>` : ""}
          ${item.error ? `<div class="file-error">${escapeHtml(cleanError(item.error))}</div>` : ""}
          ${nextStep ? `<div class="entry-text">${escapeHtml(nextStep)}</div>` : ""}
        </div>
        <div class="file-right">
          <div class="file-actions file-actions-right">
            ${url ? `<a href="${url}" download class="button secondary btn-download">Download</a>` : ""}
            ${url && jobStatus === "done" ? `<button type="button" class="danger icon-delete" title="Delete song" aria-label="Delete ${escapeHtml(title)}" data-delete-file="${escapeHtml(jobId)}:${item.entry_index}">&times;</button>` : ""}
          </div>
        </div>
      </div>
    </div>
  `;
}

function jobSummary(job) {
  const entries = job.entries || [];
  const total = entries.length;
  const ready = entries.filter((item) => item.status === "ok" && item.path).length;
  const failed = entries.filter((item) => item.status === "error").length;
  const deleted = entries.filter((item) => item.status === "deleted").length;
  const finished = ready + failed + deleted;
  if (job.status === "queued") return { style: "queued", label: "Queued", detail: `${total} ${total === 1 ? "song" : "songs"} waiting` };
  if (job.status === "processing") return { style: "processing", label: "Processing", detail: `${finished} of ${total} finished` };
  if (job.status === "error" || failed) {
    return { style: "error", label: ready ? "Completed with errors" : "Failed", detail: `${ready} of ${total} ready` };
  }
  if (!ready) return { style: "deleted", label: "No files available", detail: `${total} ${total === 1 ? "song" : "songs"}` };
  return { style: "done", label: "Ready", detail: `${ready} of ${total} ready` };
}

function jobCard(job) {
  const files = job.entries || [];
  const summary = jobSummary(job);
  const ready = files.some((item) => item.status === "ok" && item.path);
  const title = `${files.length} ${files.length === 1 ? "song" : "songs"}`;
  const updated = Number.isFinite(job.updated_at)
    ? new Date(job.updated_at * 1000).toLocaleString()
    : "";
  const filesHtml = (files && files.length)
    ? files.map((item) => fileItem(job.job_id, item, job.status)).join("")
    : `<div class="empty">No files yet.</div>`;

  const actions = `
    <div class="job-actions">
      ${job.status === "done" && ready ? `<a href="/jobs/${encodeURIComponent(job.job_id)}/download-all" class="button secondary">Download All</a>` : ""}
      ${job.status === "processing" ? `<span class="muted">Wait for processing to finish before removing this job.</span>` : `<button type="button" class="danger" data-delete-job="${escapeHtml(job.job_id)}">Remove Job</button>`}
    </div>
  `;

  return `
    <article class="job-card">
      <div class="job-row">
        ${badge(summary.style, summary.label)}
        <strong>${escapeHtml(title)}</strong>
        <span class="muted">${escapeHtml(summary.detail)}</span>
        <div class="job-row-right">
          ${updated ? `<span class="muted job-updated">Updated ${escapeHtml(updated)}</span>` : ""}
          ${actions}
        </div>
      </div>
      <div class="file-list">${filesHtml}</div>
      <div class="muted">${job.error ? escapeHtml(cleanError(job.error)) : ""}</div>
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
    await apiFetch("/enqueue", {
      method: "POST",
      body: JSON.stringify({ entries }),
    });
    submitInfo.textContent = "Job submitted.";
    entriesInput.value = "";
    updateEntryCount();
    await refreshJobs();
    jobsContainer.querySelector(".job-card")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
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

async function clearHistory() {
  if (isClearingHistory) return;
  const removable = currentJobs.filter((job) => job.status !== "processing");
  if (!removable.length) return;
  isClearingHistory = true;
  clearHistoryBtn.disabled = true;
  const processing = currentJobs.length - removable.length;
  clearHistoryMessage.textContent = `Remove ${removable.length} ${removable.length === 1 ? "job" : "jobs"} and delete their files from the server? Files already saved on your device will not be affected.` +
    (processing ? " Jobs currently processing will be kept." : "");
  clearHistoryDialog.returnValue = "cancel";
  const confirmed = new Promise((resolve) => {
    clearHistoryDialog.addEventListener("close", () => resolve(clearHistoryDialog.returnValue === "confirm"), { once: true });
  });
  clearHistoryDialog.showModal();
  if (!await confirmed) {
    isClearingHistory = false;
    clearHistoryBtn.disabled = !currentJobs.some((job) => job.status !== "processing");
    return;
  }

  historyInfo.textContent = "Clearing history...";
  try {
    const results = await Promise.allSettled(removable.map((job) =>
      apiFetch(`/jobs/${encodeURIComponent(job.job_id)}`, { method: "DELETE" })
    ));
    const cleared = results.filter((result) => result.status === "fulfilled").length;
    const skipped = processing + results.filter((result) => result.status === "rejected" && result.reason?.status === 409).length;
    const failed = results.filter((result) => result.status === "rejected" && result.reason?.status !== 409).length;
    historyInfo.textContent = `Cleared ${cleared} ${cleared === 1 ? "job" : "jobs"}.` +
      (skipped ? ` ${skipped} processing ${skipped === 1 ? "job was" : "jobs were"} kept.` : "") +
      (failed ? ` ${failed} could not be cleared; try again.` : "");
    await refreshJobs();
  } finally {
    isClearingHistory = false;
    clearHistoryBtn.disabled = !currentJobs.some((job) => job.status !== "processing");
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
    currentJobs = jobs;
    clearHistoryBtn.hidden = jobs.length === 0;
    clearHistoryBtn.disabled = isClearingHistory || !jobs.some((job) => job.status !== "processing");
    clearHistoryBtn.title = clearHistoryBtn.disabled && !isClearingHistory
      ? "Processing jobs cannot be cleared until they finish."
      : "";
    hasActiveJobs = jobs.some((job) => job.status === "queued" || job.status === "processing");
    jobsInfo.textContent = "";
    refreshBtn.hidden = true;

    if (!jobs.length) {
      jobsContainer.innerHTML = `<div class="empty"><strong>Your songs will appear here</strong><span>Add a song or link above, then select Convert songs.</span></div>`;
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
    refreshBtn.hidden = false;
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

function updateEntryCount() {
  const count = toLines(entriesInput.value).length;
  entryCount.textContent = `${count} ${count === 1 ? "song" : "songs"}`;
}

entriesInput.addEventListener("input", updateEntryCount);
refreshBtn.addEventListener("click", refreshJobs);
clearHistoryBtn.addEventListener("click", clearHistory);
submitBtn.addEventListener("click", submitJob);
document.addEventListener("visibilitychange", () => {
  clearTimeout(refreshTimer);
  if (!document.hidden) refreshJobs();
});
updateEntryCount();
refreshJobs();
