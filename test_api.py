#!/usr/bin/env python3
"""
test_api.py

Unit tests for the Flask API in api.py.
Tests endpoints and error conditions using Flask's test client.
"""

import json
import unittest
from unittest.mock import patch, MagicMock
from api import app

class TestAPI(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_download_missing_json(self):
        """Request without JSON header / content should fail with 400."""
        resp = self.app.post("/download", data="not json")
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("error_message", data)
        self.assertEqual(data["error_message"], "Request must have Content-Type: application/json")

    def test_download_missing_url(self):
        """Request with empty JSON or missing URL should fail with 400."""
        resp = self.app.post("/download", json={})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertEqual(data["error_message"], "Missing 'url' parameter in JSON body")

    def test_download_invalid_url(self):
        """Request with invalid X.com status URL should fail with 400."""
        resp = self.app.post("/download", json={"url": "https://google.com"})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("Invalid input URL", data["error_message"])

    @patch("api.extract_tweet_info")
    @patch("api.fetch_tweet_data")
    def test_download_no_media(self, mock_fetch, mock_extract):
        """If the tweet data contains no media items, should fail with 400."""
        mock_extract.return_value = ("user", "12345")
        mock_fetch.return_value = {
            "username": "user",
            "text": "Hello world without media",
            "media": []
        }
        resp = self.app.post("/download", json={"url": "https://x.com/user/status/12345"})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertEqual(data["error_message"], "No media found in this post")

    @patch("api.extract_tweet_info")
    @patch("api.fetch_tweet_data")
    @patch("urllib.request.urlopen")
    def test_download_image_success(self, mock_urlopen, mock_fetch, mock_extract):
        """Successfully returns an image stream when tweet only contains image media."""
        mock_extract.return_value = ("user", "12345")
        mock_fetch.return_value = {
            "username": "user",
            "text": "Check out this photo",
            "media": [
                {"type": "image", "url": "https://pbs.twimg.com/media/test_image.jpg"}
            ]
        }
        
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Length": "200"}
        mock_resp.read.side_effect = [b"imgdata", b""]
        mock_urlopen.return_value = mock_resp

        resp = self.app.post("/download", json={"url": "https://x.com/user/status/12345"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "application/octet-stream")
        self.assertEqual(
            resp.headers.get("Content-Disposition"),
            'attachment; filename="user_Check_out_this_photo.jpg"'
        )
        self.assertEqual(resp.data, b"imgdata")

    @patch("api.extract_tweet_info")
    @patch("api.fetch_tweet_data")
    @patch("urllib.request.urlopen")
    def test_download_success(self, mock_urlopen, mock_fetch, mock_extract):
        """Successfully returns the MP4 stream with correct headers on a valid video tweet URL."""
        mock_extract.return_value = ("user", "12345")
        mock_fetch.return_value = {
            "username": "user",
            "text": "Hello world #video",
            "media": [
                {"type": "video", "url": "https://video.twimg.com/video.mp4"}
            ]
        }
        
        # Mock the urllib response
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Length": "100"}
        mock_resp.read.side_effect = [b"chunk1", b"chunk2", b""]
        mock_urlopen.return_value = mock_resp

        resp = self.app.post("/download", json={"url": "https://x.com/user/status/12345"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "application/octet-stream")
        self.assertEqual(resp.headers.get("Content-Length"), "100")
        self.assertEqual(
            resp.headers.get("Content-Disposition"),
            'attachment; filename="user_Hello_world.mp4"'
        )
        self.assertEqual(resp.data, b"chunk1chunk2")

    @patch("api.extract_tweet_info")
    @patch("api.fetch_tweet_data")
    @patch("urllib.request.urlopen")
    def test_download_source_connect_fail(self, mock_urlopen, mock_fetch, mock_extract):
        """If connecting to the media URL fails, return 502 with error message."""
        mock_extract.return_value = ("user", "12345")
        mock_fetch.return_value = {
            "username": "user",
            "text": "Hello world",
            "media": [
                {"type": "video", "url": "https://video.twimg.com/video.mp4"}
            ]
        }
        
        # Simulate connection error to media source
        mock_urlopen.side_effect = Exception("Connection timed out")

        resp = self.app.post("/download", json={"url": "https://x.com/user/status/12345"})
        self.assertEqual(resp.status_code, 502)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("Failed to connect to media source URL", data["error_message"])

    @patch("api.extract_tweet_info")
    @patch("api.fetch_tweet_data")
    @patch("urllib.request.urlopen")
    def test_download_multiple_media_zip(self, mock_urlopen, mock_fetch, mock_extract):
        """When post has multiple media items and no index, streams a ZIP archive containing all files."""
        import zipfile
        import io

        mock_extract.return_value = ("user", "12345")
        mock_fetch.return_value = {
            "username": "user",
            "text": "Photo and video",
            "media": [
                {"type": "image", "url": "https://pbs.twimg.com/media/photo.jpg"},
                {"type": "video", "url": "https://video.twimg.com/clip.mp4"}
            ]
        }

        # Mock urllib.request.urlopen context manager for both requests
        resp1 = MagicMock()
        resp1.read.side_effect = [b"photo_bytes", b""]
        resp1.__enter__.return_value = resp1

        resp2 = MagicMock()
        resp2.read.side_effect = [b"video_bytes", b""]
        resp2.__enter__.return_value = resp2

        mock_urlopen.side_effect = [resp1, resp2]

        resp = self.app.post("/download", json={"url": "https://x.com/user/status/12345"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "application/zip")
        self.assertEqual(
            resp.headers.get("Content-Disposition"),
            'attachment; filename="user_Photo_and_video.zip"'
        )

        # Verify zip archive content
        zf = zipfile.ZipFile(io.BytesIO(resp.data))
        file_names = zf.namelist()
        self.assertIn("user_Photo_and_video_1.jpg", file_names)
        self.assertIn("user_Photo_and_video_2.mp4", file_names)
        self.assertEqual(zf.read("user_Photo_and_video_1.jpg"), b"photo_bytes")
        self.assertEqual(zf.read("user_Photo_and_video_2.mp4"), b"video_bytes")
        self.assertIn("user_Photo_and_video.json", file_names)
        meta = json.loads(zf.read("user_Photo_and_video.json").decode("utf-8"))
        self.assertEqual(meta["username"], "user")
        self.assertEqual(meta["status_id"], "12345")
        self.assertEqual(meta["content"], "Photo and video")
        self.assertEqual(len(meta["media"]), 2)

    @patch("api.extract_tweet_info")
    @patch("api.fetch_tweet_data")
    @patch("urllib.request.urlopen")
    def test_download_specific_index_success(self, mock_urlopen, mock_fetch, mock_extract):
        """When index is provided for multiple media post, only download the requested index as direct file."""
        mock_extract.return_value = ("user", "12345")
        mock_fetch.return_value = {
            "username": "user",
            "text": "Photo and video",
            "media": [
                {"type": "image", "url": "https://pbs.twimg.com/media/photo.jpg"},
                {"type": "video", "url": "https://video.twimg.com/clip.mp4"}
            ]
        }

        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Length": "123"}
        mock_resp.read.side_effect = [b"video_data", b""]
        mock_urlopen.return_value = mock_resp

        resp = self.app.post("/download", json={"url": "https://x.com/user/status/12345", "index": 2})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "application/octet-stream")
        self.assertEqual(
            resp.headers.get("Content-Disposition"),
            'attachment; filename="user_Photo_and_video_2.mp4"'
        )
        self.assertEqual(resp.data, b"video_data")

    @patch("api.extract_tweet_info")
    @patch("api.fetch_tweet_data")
    def test_download_invalid_index(self, mock_fetch, mock_extract):
        """Invalid index values (out of range or <= 0) should return 400."""
        mock_extract.return_value = ("user", "12345")
        mock_fetch.return_value = {
            "username": "user",
            "text": "One photo",
            "media": [{"type": "image", "url": "https://pbs.twimg.com/media/photo.jpg"}]
        }

        # Index <= 0
        resp = self.app.post("/download", json={"url": "https://x.com/user/status/12345", "index": 0})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("'index' must be a positive integer", data["error_message"])

        # Index out of bounds
        resp = self.app.post("/download", json={"url": "https://x.com/user/status/12345", "index": 5})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("out of range", data["error_message"])

    def test_get_tweet_missing_url(self):
        """GET /tweet without 'url' parameter returns 400."""
        resp = self.app.get("/tweet")
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertEqual(data["error_message"], "Missing 'url' query parameter")

    def test_get_tweet_invalid_url(self):
        """GET /tweet with invalid URL returns 400."""
        resp = self.app.get("/tweet?url=https://google.com")
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("Invalid input URL", data["error_message"])

    @patch("api.extract_tweet_info")
    @patch("api.fetch_tweet_data")
    def test_get_tweet_success(self, mock_fetch, mock_extract):
        """GET /tweet with valid URL returns JSON containing username, tweet content, etc."""
        mock_extract.return_value = ("testuser", "987654321")
        mock_fetch.return_value = {
            "username": "testuser",
            "text": "This is a great tweet #awesome",
            "date": "2026-11-07 12:00:00",
            "likes": 42,
            "retweets": 10,
            "replies": 5,
            "media": [{"url": "https://pbs.twimg.com/media/pic.jpg", "type": "image"}]
        }
        resp = self.app.get("/tweet?url=https://x.com/testuser/status/987654321")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertEqual(data["username"], "testuser")
        self.assertEqual(data["content"], "This is a great tweet #awesome")
        self.assertEqual(data["text"], "This is a great tweet #awesome")
        self.assertEqual(data["status_id"], "987654321")
        self.assertEqual(data["date"], "2026-11-07 12:00:00")
        self.assertEqual(data["likes"], 42)
        self.assertEqual(data["retweets"], 10)
        self.assertEqual(data["replies"], 5)
        self.assertEqual(len(data["media"]), 1)

    @patch("api.extract_tweet_info")
    @patch("api.fetch_tweet_data")
    def test_get_tweet_fetch_error(self, mock_fetch, mock_extract):
        """GET /tweet returns 500 when fetch_tweet_data raises an error."""
        mock_extract.return_value = ("testuser", "987654321")
        mock_fetch.side_effect = Exception("API unreachable")
        resp = self.app.get("/tweet?url=https://x.com/testuser/status/987654321")
        self.assertEqual(resp.status_code, 500)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("Error fetching tweet metadata", data["error_message"])

if __name__ == "__main__":
    unittest.main()
