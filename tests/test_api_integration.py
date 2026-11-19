"""API and worker integration tests; downloads are simulated, not networked."""
import tempfile
import io
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

try:
    import api
    import job_store
    import worker
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    api = None


@unittest.skipIf(api is None, "install requirements-test.txt to run API integration tests")
class ApiIntegrationTests(unittest.TestCase):
    def test_enqueue_worker_session_download_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs, music = Path(directory) / "jobs", Path(directory) / "music"
            jobs.mkdir()
            music.mkdir()

            def fake_download(entry, output_dir):
                target = Path(output_dir) / "song [c5ebb0bb59f142d6baeafa4d597f8d14].mp3"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"test audio")
                return {"input": entry, "status": "ok", "path": str(target)}

            with patch.object(api, "JOB_DIR", jobs), patch.object(api, "MUSIC_DIR", music), \
                 patch.object(job_store, "JOB_DIR", jobs), patch.object(worker, "JOB_DIR", jobs), \
                 patch.object(worker, "OUT_DIR", music), patch.object(worker, "process_entry", fake_download):
                # Separate clients maintain separate anonymous session cookies.
                with TestClient(api.app) as owner, TestClient(api.app) as stranger:
                    response = owner.post("/enqueue", json={"entries": ["Artist - Song", "Artist - Song"]})
                    self.assertEqual(response.status_code, 200, response.text)
                    job_id = response.json()["job_id"]
                    self.assertEqual(stranger.get(f"/jobs/{job_id}").status_code, 404)
                    self.assertEqual(stranger.get(f"/jobs/{job_id}/files/0/download").status_code, 404)
                    queued = jobs / f"{job_id}.json"
                    processing = jobs / f"{job_id}.processing"
                    queued.rename(processing)
                    self.assertEqual(owner.delete(f"/jobs/{job_id}").status_code, 409)
                    processing.rename(queued)
                    # Stop the worker after its first polling pass.
                    with patch.object(worker.time, "sleep", side_effect=KeyboardInterrupt):
                        with self.assertRaises(KeyboardInterrupt):
                            worker.run_worker()
                    listing = owner.get("/jobs").json()["jobs"]
                    self.assertEqual(listing[0]["status"], "done")
                    self.assertEqual(listing[0]["entries"][0]["status"], "ok")
                    download = owner.get(f"/jobs/{job_id}/files/0/download")
                    self.assertEqual(download.status_code, 200)
                    self.assertEqual(download.content, b"test audio")
                    self.assertIn('filename="song.mp3"', download.headers["content-disposition"])
                    archive = owner.get(f"/jobs/{job_id}/download-all")
                    self.assertEqual(archive.status_code, 200)
                    with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
                        self.assertEqual(sorted(zipped.namelist()), ["song (2).mp3", "song.mp3"])
                    with patch.object(api, "MAX_ZIP_BYTES", 1):
                        self.assertEqual(owner.get(f"/jobs/{job_id}/download-all").status_code, 413)
                    self.assertEqual(owner.delete(f"/jobs/{job_id}/files/0").status_code, 200)
                    self.assertEqual(owner.get(f"/jobs/{job_id}/files/0/download").status_code, 404)
                    self.assertEqual(owner.get(f"/jobs/{job_id}/files/1/download").content, b"test audio")
                    self.assertEqual(owner.delete(f"/jobs/{job_id}").status_code, 200)
                    self.assertFalse((music / job_id).exists())

    def test_blank_entries_are_rejected(self):
        with TestClient(api.app) as client:
            self.assertEqual(client.post("/enqueue", json={"entries": [" "]}).status_code, 422)
