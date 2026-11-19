"""Exercise cleanup with lightweight web-framework stubs, without a server."""
import importlib
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import job_store


class StubApp:
    def __init__(self, *args, **kwargs):
        pass

    def mount(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return lambda *args, **kwargs: lambda function: function


class StubHTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


def import_api():
    fastapi = types.ModuleType("fastapi")
    setattr(fastapi, "FastAPI", StubApp)
    setattr(fastapi, "HTTPException", StubHTTPException)
    setattr(fastapi, "Request", object)
    setattr(fastapi, "Response", object)
    responses = types.ModuleType("fastapi.responses")
    setattr(responses, "FileResponse", object)
    setattr(responses, "StreamingResponse", object)
    staticfiles = types.ModuleType("fastapi.staticfiles")
    setattr(staticfiles, "StaticFiles", lambda **kwargs: None)
    pydantic = types.ModuleType("pydantic")
    setattr(pydantic, "BaseModel", object)
    setattr(pydantic, "field_validator", lambda *args: lambda function: function)
    with patch.dict(sys.modules, {"fastapi": fastapi, "fastapi.responses": responses,
                                 "fastapi.staticfiles": staticfiles, "pydantic": pydantic}):
        return importlib.import_module("api")


class CleanupTests(unittest.TestCase):
    def test_job_list_includes_entries_only_for_current_session(self):
        api = import_api()
        with tempfile.TemporaryDirectory() as directory:
            jobs = Path(directory)
            job_store.write_json(jobs / "00000000-0000-0000-0000-000000000001.done",
                                 {"owner_id": "mine", "results": [{"input": "Song", "status": "ok", "path": "music/song.mp3"}]})
            job_store.write_json(jobs / "00000000-0000-0000-0000-000000000002.json",
                                 {"owner_id": "other", "entries": ["Private"]})
            request = types.SimpleNamespace(cookies={api.SESSION_COOKIE_NAME: "mine"})
            with patch.object(api, "JOB_DIR", jobs), patch.object(job_store, "JOB_DIR", jobs):
                result = api.list_my_jobs(request, object())
            self.assertEqual(len(result["jobs"]), 1)
            self.assertEqual(result["jobs"][0]["entries"][0]["input"], "Song")
            self.assertEqual(result["jobs"][0]["status"], "done")

    def test_expired_terminal_and_stale_processing_jobs(self):
        api = import_api()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs, music = root / "jobs", root / "music"
            jobs.mkdir()
            music.mkdir()
            now = time.time()
            old_done = jobs / "old.done"
            fresh_done = jobs / "fresh.done"
            stale = jobs / "stale.processing"
            active = jobs / "active.processing"
            queued = jobs / "queued.json"
            for path, data in [(old_done, {"completed_at": now - 400000}),
                               (fresh_done, {"completed_at": now}),
                               (stale, {"owner_id": "owner", "entries": ["song"]}),
                               (active, {"owner_id": "owner"}), (queued, {})]:
                job_store.write_json(path, data)
            os.utime(stale, (now - 600, now - 600))
            os.utime(queued, (now - 400000, now - 400000))
            with patch.object(api, "JOB_DIR", jobs), patch.object(api, "MUSIC_DIR", music), \
                 patch.object(job_store, "JOB_DIR", jobs), patch.object(api, "TTL_SECONDS", 259200), \
                 patch.object(api, "STALE_JOB_SECONDS", 300):
                api._cleanup_once()
            self.assertFalse(old_done.exists())
            self.assertTrue(fresh_done.exists())
            self.assertTrue(active.exists())
            self.assertTrue(queued.exists())
            self.assertFalse(stale.exists())
            failed = json.loads((jobs / "stale.err").read_text(encoding="utf-8"))
            self.assertEqual(failed["owner_id"], "owner")
            self.assertEqual(failed["status"], "error")


if __name__ == "__main__":
    unittest.main()
