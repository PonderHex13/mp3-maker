import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

import job_store


def increment(directory, iterations):
    job_store.JOB_DIR = Path(directory)
    path = job_store.JOB_DIR / "counter.json"
    for _ in range(iterations):
        with job_store.queue_lock():
            data = json.loads(path.read_text(encoding="utf-8"))
            job_store.write_json(path, {"count": data["count"] + 1})


class JobStoreTests(unittest.TestCase):
    def test_atomic_write_preserves_existing_file_on_serialization_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            job_store.write_json(path, {"value": "old"})
            with self.assertRaises(TypeError):
                job_store.write_json(path, {"value": object()})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": "old"})
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["job.json"])

    def test_lock_serializes_multiple_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "counter.json"
            job_store.write_json(path, {"count": 0})
            processes = [multiprocessing.Process(target=increment, args=(directory, 20)) for _ in range(3)]
            for process in processes:
                process.start()
            for process in processes:
                process.join(20)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["count"], 60)


if __name__ == "__main__":
    unittest.main()
