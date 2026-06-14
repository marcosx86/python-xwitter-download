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
    def test_download_no_video(self, mock_fetch, mock_extract):
        """If the tweet data contains no video media, should fail with 400."""
        mock_extract.return_value = ("user", "12345")
        mock_fetch.return_value = {
            "username": "user",
            "text": "Hello world",
            "media": [
                {"type": "image", "url": "https://pbs.twimg.com/media/image.jpg"}
            ]
        }
        resp = self.app.post("/download", json={"url": "https://x.com/user/status/12345"})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertEqual(data["error_message"], "No video media found in this post")

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
        """If connecting to the video URL fails, return 502 with error message."""
        mock_extract.return_value = ("user", "12345")
        mock_fetch.return_value = {
            "username": "user",
            "text": "Hello world",
            "media": [
                {"type": "video", "url": "https://video.twimg.com/video.mp4"}
            ]
        }
        
        # Simulate connection error to video source
        mock_urlopen.side_effect = Exception("Connection timed out")

        resp = self.app.post("/download", json={"url": "https://x.com/user/status/12345"})
        self.assertEqual(resp.status_code, 502)
        data = json.loads(resp.data.decode("utf-8"))
        self.assertIn("Failed to connect to video source URL", data["error_message"])

if __name__ == "__main__":
    unittest.main()
