const jobsContainer = document.getElementById("jobsContainer");
const submitBtn = document.getElementById("submitBtn");
const submitInfo = document.getElementById("submitInfo");
const entriesInput = document.getElementById("entries");

const REFRESH_MS = 3000;
let isRefreshing = false;

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

  // Support pasted test-data style input where entries are quoted in one line:
  // "Artist - Song" "https://..." "Another Artist - Song"
  const quotedMatches = Array.from(raw.matchAll(/"([^"]+)"/g)).map((m) => m[1].trim());
  if (quotedMatches.length > 0) {
    return quotedMatches.filter((line) => line.length > 0);
  }

  // Default: one entry per line.
  return raw
    .split(/\r?\n/)
    .map((line) => line.trim())
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
    const message = body?.detail || `${response.status} ${response.statusText}`;
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
  const url = path ? `/music/${encodeURIComponent(path.split(/[\\/]/).pop())}` : null;
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
            ${url ? `<a href="${url}" download><button type="button" class="secondary btn-download">Download</button></a>` : ""}
            ${status === "ok" ? `<button type="button" class="danger icon-delete" title="Delete Song" aria-label="Delete Song" data-delete-file="${jobId}:${item.entry_index}">&times;</button>` : status === "deleted" ? `<button type="button" class="secondary icon-delete" disabled>&times;</button>` : ""}
          </div>
        </div>
      </div>
    </div>
  `;
}

function jobCard(job, details, files) {
  const filesHtml = (files && files.length)
    ? files.map((item) => fileItem(job.job_id, item)).join("")
    : `<div class="empty">No files yet.</div>`;

  const actions = `
    <div class="file-actions">
      ${job.status === "done" ? `<a href="/jobs/${job.job_id}/download-all" target="_blank" rel="noopener"><button type="button" class="secondary">Download All</button></a>` : ""}
      <button type="button" class="danger" data-delete-job="${job.job_id}">Clear Job</button>
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
      <div class="muted">${details?.error ? escapeHtml(details.error) : ""}</div>
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
  if (isRefreshing) return;
  isRefreshing = true;

  try {
    const list = await apiFetch("/jobs");
    const jobs = list.jobs || [];

    if (!jobs.length) {
      jobsContainer.innerHTML = `<div class="empty">No jobs yet. Submit entries above.</div>`;
      return;
    }

    const detailed = await Promise.all(
      jobs.map(async (job) => {
        let details = null;
        let files = [];

        try {
          details = await apiFetch(`/jobs/${job.job_id}`);
        } catch {
          details = null;
        }

        try {
          const fileResp = await apiFetch(`/jobs/${job.job_id}/files`);
          files = fileResp.entries || [];
        } catch {
          files = [];
        }

        return { job, details, files };
      })
    );

    jobsContainer.innerHTML = detailed
      .map(({ job, details, files }) => jobCard(job, details, files))
      .join("");

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
    jobsContainer.innerHTML = `<div class="empty">Error loading jobs: ${escapeHtml(err.message)}</div>`;
  } finally {
    isRefreshing = false;
  }
}

submitBtn.addEventListener("click", submitJob);
refreshJobs();
setInterval(refreshJobs, REFRESH_MS);
