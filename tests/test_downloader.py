import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

with patch.dict(sys.modules, {"yt_dlp": types.ModuleType("yt_dlp")}):
    downloader = importlib.import_module("mp3_maker")


class DownloaderTests(unittest.TestCase):
    def test_url_hosts_are_checked_not_substrings(self):
        self.assertEqual(downloader.detect_url_type("https://music.youtube.com/watch?v=1"), "youtube")
        self.assertEqual(downloader.detect_url_type("https://youtu.be/abc"), "youtube")
        self.assertEqual(downloader.detect_url_type("https://youtube.com.attacker.test/watch"), "unknown")
        self.assertEqual(downloader.detect_url_type("https://attacker.test/youtube.com"), "unknown")
        self.assertEqual(downloader.detect_url_type("https://open.spotify.com/track/1"), "spotify")

    def test_shared_entry_parser_and_batch_order(self):
        with patch.object(downloader, "download_title_as_mp3", side_effect=lambda name, author, output_dir: f"{author}:{name}"):
            results = downloader.process_batch_entries(["A - One", "B | Two", "missing separator", " - title"], concurrency=2)
        self.assertEqual([result["input"] for result in results], ["A - One", "B | Two", "missing separator", "- title"])
        self.assertEqual([result["status"] for result in results], ["ok", "ok", "error", "error"])
        self.assertEqual(results[0]["path"], "A:One")

    def test_unsupported_urls_raise_or_return_errors(self):
        with self.assertRaises(ValueError):
            downloader.download_link_as_mp3("https://open.spotify.com/track/1")
        result = downloader.process_entry("https://example.com/youtube.com")
        self.assertEqual(result["status"], "error")

    def test_never_returns_an_unrelated_existing_mp3(self):
        class FakeYDL:
            def __init__(self, options):
                self.options = options
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download):
                return {"title": "song", "ext": "webm"}
            def prepare_filename(self, info):
                return self.options["outtmpl"].replace("%(title)s", info["title"]).replace("%(ext)s", info["ext"])

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "unrelated.mp3").write_bytes(b"old")
            with patch.object(downloader.yt_dlp, "YoutubeDL", FakeYDL, create=True):
                with self.assertRaises(FileNotFoundError):
                    downloader.download_youtube_as_mp3("https://youtu.be/abc", directory)

            def create_output(ydl, url, download):
                info = {"title": "song", "ext": "webm"}
                path = Path(ydl.prepare_filename(info)).with_suffix(".mp3")
                path.write_bytes(b"new audio")
                return info

            with patch.object(FakeYDL, "extract_info", create_output), \
                 patch.object(downloader.yt_dlp, "YoutubeDL", FakeYDL, create=True):
                result = downloader.download_youtube_as_mp3("https://youtu.be/abc", directory)
            self.assertEqual(Path(result).read_bytes(), b"new audio")


if __name__ == "__main__":
    unittest.main()
