---
description: "Generate Docker and deployment files to containerize MP3 Maker for OCI with Traefik. Use when: containerize, docker, k3s, deploy, traefik, OCI, production."
agent: agent
argument-hint: "Target: 'docker-compose', 'k3s', or both (default: both)"
---

Generate the Docker and deployment configuration to containerize the MP3 Maker app for production on OCI (Oracle Cloud Infrastructure) with Traefik as the reverse proxy.

Read [AGENTS.md](../../AGENTS.md) first — it documents the architecture, shared volumes, and deployment constraints before writing any files.

## What to Generate

Based on the user's argument (or both if unspecified):

---

### Option A: Docker Compose (for a single OCI VM with Docker)

Generate these files:

**`Dockerfile`**
- Base: `python:3.12-slim`
- Install system `ffmpeg` via `apt-get` (do NOT copy Windows `.exe` binaries)
- Copy `requirements.txt` and run `pip install --no-cache-dir -r requirements.txt`
- Install `spotdl` if not already in requirements.txt: `pip install spotdl`
- Copy app source files: `api.py`, `worker.py`, `mp3_maker.py`, `static/`
- Do NOT copy `jobs/`, `music/`, `output/`, `ffmpeg/` (these are volumes or irrelevant)
- Default `CMD`: `["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]`

**`docker-compose.yml`**
- `api` service: uses the image, exposes port 8000, Traefik labels for routing + TLS
- `worker` service: same image, `command: python worker.py`, no exposed ports
- Both services mount `./jobs:/app/jobs` and `./music:/app/music` (shared volumes)
- `DOMAIN` variable via `.env` file
- Traefik labels:
  - `traefik.enable=true`
  - `traefik.http.routers.<name>.rule=Host(\`${DOMAIN}\`)`
  - `traefik.http.routers.<name>.tls.certresolver=letsencrypt`
  - `traefik.http.services.<name>.loadbalancer.server.port=8000`

**`.env.example`**
- `DOMAIN=mp3.yourdomain.com`
- `LETSENCRYPT_EMAIL=you@example.com`

**`traefik/traefik.yml`** (static Traefik config)
- entrypoints: `web` (80 → redirect to websecure), `websecure` (443)
- providers: `docker` with `exposedByDefault: false`
- certificatesResolvers: `letsencrypt` using ACME HTTP challenge

---

### Option B: k3s / Kubernetes Manifests

Generate these files under `k8s/`:

**`k8s/namespace.yaml`** — `mp3-maker` namespace

**`k8s/pvc.yaml`** — `PersistentVolumeClaim` for `jobs/` and `music/` (ReadWriteMany if NFS/OCI FSS, or ReadWriteOnce if single-node)

**`k8s/deployment-api.yaml`**
- Image: ghcr.io/<user>/mp3-maker:latest (placeholder)
- Port 8000
- Volume mounts for both PVCs
- Resource limits (suggest: 256Mi memory, 250m CPU)

**`k8s/deployment-worker.yaml`**
- Same image, `command: ["python", "worker.py"]`
- Same volume mounts

**`k8s/service.yaml`** — ClusterIP service pointing to api deployment, port 8000

**`k8s/ingressroute.yaml`** — Traefik `IngressRoute` CRD:
```yaml
apiVersion: traefik.containo.us/v1alpha1
kind: IngressRoute
```
- Route to api service on port 8000
- TLS with `certResolver: letsencrypt`

**`k8s/middleware.yaml`** (optional) — Traefik `Middleware` for BasicAuth or rate limiting

---

## After Generating Files

1. List every file created with a one-line description
2. Print the exact commands to build and start the stack:
   - Docker Compose: `docker compose up -d --build`
   - k3s: `kubectl apply -f k8s/`
3. Call out any manual steps required:
   - DNS A record pointing domain to OCI public IP
   - Opening OCI security list ports 80 and 443
   - Setting `DOMAIN` and `LETSENCRYPT_EMAIL` in `.env`
4. Note the security gaps that should be addressed before going public:
   - `/music` is unauthenticated — suggest Traefik BasicAuth middleware
   - No rate limit on `POST /enqueue`
   - Worker crash leaves `.processing` files — suggest a cleanup cron or init container
