import importlib
import sys
import tempfile
import io
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from mutagen.id3 import ID3

with patch.dict(sys.modules, {"yt_dlp": types.ModuleType("yt_dlp")}):
    downloader = importlib.import_module("mp3_maker")


class DownloaderTests(unittest.TestCase):
    def test_song_filename_prefers_metadata_and_removes_common_labels(self):
        metadata = {"artist": "Oasis", "track": "Champagne Supernova (Remastered)"}
        self.assertEqual(downloader._song_filename(metadata), "Oasis - Champagne Supernova")
        self.assertEqual(downloader._song_filename(metadata, "Oazis", "Champagne Supernovaa"), "Oasis - Champagne Supernova")
        self.assertEqual(downloader._song_filename({}, "My Artist", "My Song (Official Video)"), "My Artist - My Song")
        self.assertEqual(downloader._song_filename({"title": "Oasis - Wonderwall (Official Video)"}, "Oazis", "Wonderwalll"), "Oasis - Wonderwall")
        self.assertEqual(downloader._song_filename({"artist": "Oasis"}, "Oazis", "Wonderwall"), "Oasis - Wonderwall")
        self.assertEqual(downloader._song_filename({"track": "Wonderwall"}, "Oasis", "Wonderwalll"), "Oasis - Wonderwall")
        self.assertEqual(downloader._song_filename({"title": "Artist - Song (Live)"}), "Artist - Song (Live)")
        self.assertEqual(downloader._song_filename({"title": "Song", "uploader": "Artist - Topic"}), "Artist - Song")
        self.assertEqual(downloader._song_filename({"title": "Song"}), "Unknown Artist - Song")
        self.assertEqual(downloader._song_filename({"artist": "A/B", "track": "Song: Title"}), "A_B - Song_ Title")

    def test_tags_preserve_original_characters_and_other_metadata(self):
        from mutagen.id3 import TALB
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "track.mp3"
            path.write_bytes(b"audio")
            initial = ID3()
            initial.add(TALB(encoding=3, text=["Album"]))
            initial.save(path)
            downloader._write_song_tags(path, "AC/DC", "Song: Title")
            tags = ID3(path)
            self.assertEqual(tags["TPE1"].text, ["AC/DC"])
            self.assertEqual(tags["TIT2"].text, ["Song: Title"])
            self.assertEqual(tags["TALB"].text, ["Album"])

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
            downloader.download_link_as_mp3("https://open.spotify.com/playlist/1")
        result = downloader.process_entry("https://example.com/youtube.com")
        self.assertEqual(result["status"], "error")

    def test_terminal_color_codes_are_removed_from_errors(self):
        with patch.object(downloader, "download_link_as_mp3", side_effect=ValueError("\x1b[0;31mERROR:\x1b[0m HTTP 403")):
            result = downloader.process_entry("https://youtu.be/example")
        self.assertEqual(result["error"], "ERROR: HTTP 403")

    def test_spotify_track_uses_title_to_search_youtube(self):
        url = "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp?si=example"
        with patch.object(downloader, "urlopen", return_value=io.BytesIO(b'{"title":"Mr. Brightside"}')) as lookup, \
             patch.object(downloader, "_download_search", return_value="music/song.mp3") as search:
            self.assertEqual(downloader.download_link_as_mp3(url), "music/song.mp3")
        search.assert_called_once_with("Mr. Brightside", "output")
        self.assertIn("open.spotify.com%2Ftrack%2F3n3Ppam7vgaVa1iaRUc9Lp", lookup.call_args.args[0])

    def test_spotify_lookup_failure_is_reported(self):
        url = "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp"
        with patch.object(downloader, "urlopen", side_effect=OSError("network error")):
            result = downloader.process_entry(url)
        self.assertEqual(result["status"], "error")
        self.assertIn("Spotify track information", result["error"])

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
            self.assertTrue(Path(result).read_bytes().endswith(b"new audio"))
            self.assertEqual(ID3(result)["TPE1"].text, ["Unknown Artist"])
            self.assertEqual(ID3(result)["TIT2"].text, ["song"])


if __name__ == "__main__":
    unittest.main()
