---
description: "Review this project's Python code for bugs, security issues, and improvements. Use when: code review, audit, check code, suggest improvements."
agent: agent
argument-hint: "File or area to review (leave blank for full project)"
---

Review the MP3 Maker codebase for bugs, security issues, and improvement opportunities. Focus on the areas listed below. Be specific — include file name, line numbers, and a suggested fix for each finding.

## Files to Review

- [api.py](../../api.py) — FastAPI endpoints, session handling, job management
- [worker.py](../../worker.py) — File-queue worker, job claiming, concurrency
- [mp3_maker.py](../../mp3_maker.py) — Core downloader, ffmpeg detection, yt-dlp/spotdl integration
- [static/app.js](../../static/app.js) — Frontend JS (fetch calls, DOM, error handling)

If the user specified a file or area in their message, focus there. Otherwise review all files.

## Review Checklist

### Security
- [ ] **Path traversal**: Is `job_id` from URL params validated as a UUID before being used to construct file paths?
- [ ] **Input sanitization**: Are `entries` strings from `POST /enqueue` passed unsanitized to yt-dlp/spotdl subprocesses?
- [ ] **Cookie flags**: Is the session cookie set with `httponly=True` and `samesite="lax"`?
- [ ] **Open file serving**: Is `/music` publicly accessible without auth? Flag if deployed publicly.
- [ ] **Rate limiting**: Is `POST /enqueue` rate-limited or capped in any way?

### Reliability
- [ ] **Crash recovery**: If the worker crashes mid-job, is the `.processing` file left forever? Suggest a recovery/timeout mechanism.
- [ ] **Race condition**: The file-rename claim mechanism is only safe with a single worker — document or enforce this.
- [ ] **Error propagation**: Are errors from yt-dlp/spotdl captured and surfaced in `.err` files with enough detail?
- [ ] **Disk space**: Is there any guard against filling the disk with MP3 files?

### Code Quality
- [ ] **Hardcoded config**: Are `JOB_DIR`, `TTL_HOURS`, port, etc. hardcoded? Suggest `os.environ.get()` with defaults.
- [ ] **Magic strings**: File suffixes (`.done`, `.err`, `.processing`) — are they defined as constants?
- [ ] **Type hints**: Are public functions typed? (Python 3.10+ union syntax `X | Y` is fine here)
- [ ] **Thread safety**: The background cleanup thread — does it safely handle concurrent file access?

### Frontend (app.js)
- [ ] **Error display**: Are fetch errors shown to the user or silently swallowed?
- [ ] **XSS**: Are user-supplied strings (song titles, URLs) inserted into the DOM with `innerHTML`? Prefer `textContent`.
- [ ] **Polling**: Is the 3-second auto-refresh cancelled when the tab is hidden or jobs are all complete?

## Output Format

For each finding, use this format:

**[SEVERITY: High/Medium/Low]** `filename.py:line` — Short description  
> What the problem is and why it matters  
> Suggested fix (code snippet if helpful)

At the end, provide a brief summary table:

| Area | Findings | Highest Severity |
|------|----------|-----------------|
| Security | N | ... |
| Reliability | N | ... |
| Code Quality | N | ... |
| Frontend | N | ... |
