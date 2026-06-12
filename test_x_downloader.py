#!/usr/bin/env python3
"""
test_x_downloader.py

Unit tests for x_downloader.py verifying url transformation,
filename sanitization, image URL quality rewriting, and extension retrieval.
"""

import json
import unittest
import unittest.mock
from x_downloader import (
    extract_tweet_info,
    sanitize_filename,
    get_highest_quality_image_url,
    get_file_extension,
)


class TestXDownloader(unittest.TestCase):
    """Unit test suite for the X.com downloader helper functions."""

    def test_extract_tweet_info_valid(self):
        """Tests that valid X.com/Twitter.com URLs are correctly parsed to get username and status ID."""
        test_cases = [
            (
                "https://x.com/Twitter/status/1577730467436138524",
                ("Twitter", "1577730467436138524"),
            ),
            (
                "http://twitter.com/elonmusk/status/1234567890?s=21&t=abc",
                ("elonmusk", "1234567890"),
            ),
            (
                "https://fixupx.com/jack/status/20",
                ("jack", "20"),
            ),
            (
                "https://fxtwitter.com/username/status/987654321/",
                ("username", "987654321"),
            ),
        ]
        for url, expected in test_cases:
            with self.subTest(url=url):
                self.assertEqual(extract_tweet_info(url), expected)

    def test_extract_tweet_info_invalid(self):
        """Tests that invalid URLs raise a ValueError."""
        invalid_urls = [
            "ftp://x.com/Twitter/status/1577730467436138524",
            "https://google.com/search?q=twitter",
            "https://x.com/Twitter",
            "https://x.com/Twitter/status/",
            "https://twitter.com/status/123456",  # missing username
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    extract_tweet_info(url)

    def test_sanitize_filename(self):
        """Tests the filename generation logic, checking hashtag stripping, word limits, and sanitization."""
        # Simple test
        self.assertEqual(
            sanitize_filename("alice", "Hello World"),
            "alice_Hello_World",
        )

        # Strip hashtags (remove entire word starting with '#')
        self.assertEqual(
            sanitize_filename("bob", "My new post #awesome #coding!"),
            "bob_My_new_post",
        )

        # First line only
        self.assertEqual(
            sanitize_filename("charlie", "First line of text\nSecond line here"),
            "charlie_First_line_of_text",
        )

        # 10 words limit
        self.assertEqual(
            sanitize_filename(
                "dave",
                "one two three four five six seven eight nine ten eleven twelve",
            ),
            "dave_one_two_three_four_five_six_seven_eight_nine_ten",
        )

        # Special characters escape and multiple underscores collapse
        self.assertEqual(
            sanitize_filename("emma", "Hello!!! @World... How's it going?"),
            "emma_Hello_World_How_s_it_going",
        )

        # Fallback when empty or only hashtags
        self.assertEqual(
            sanitize_filename("frank", "#just #hashtags"),
            "frank_tweet",
        )
        self.assertEqual(
            sanitize_filename("grace", ""),
            "grace_tweet",
        )

    def test_get_highest_quality_image_url(self):
        """Tests that Twitter image URLs are correctly updated to request 'orig' format/name."""
        # With format/name parameters
        self.assertEqual(
            get_highest_quality_image_url(
                "https://pbs.twimg.com/media/FeU5fhPXkCoZXZB?format=jpg&name=large"
            ),
            "https://pbs.twimg.com/media/FeU5fhPXkCoZXZB?format=jpg&name=orig",
        )

        # Direct path with no query
        self.assertEqual(
            get_highest_quality_image_url(
                "https://pbs.twimg.com/media/FeU5fhPXkCoZXZB.jpg"
            ),
            "https://pbs.twimg.com/media/FeU5fhPXkCoZXZB.jpg?name=orig",
        )

        # Non-twitter URL (should not be modified)
        self.assertEqual(
            get_highest_quality_image_url("https://example.com/image.jpg?size=large"),
            "https://example.com/image.jpg?size=large",
        )

    def test_get_file_extension(self):
        """Tests extracting the file extension from URL or fallback media type."""
        # Simple extension in path
        self.assertEqual(get_file_extension("https://example.com/media/video.mp4"), "mp4")

        # Format parameter in query string
        self.assertEqual(
            get_file_extension("https://pbs.twimg.com/media/FeU5fhPXkCoZXZB?format=png&name=orig"),
            "png",
        )

        # Fallback to type 'video'
        self.assertEqual(
            get_file_extension("https://example.com/stream/123", media_type="video"),
            "mp4",
        )

        # Fallback to type 'image'
        self.assertEqual(
            get_file_extension("https://example.com/stream/123", media_type="image"),
            "jpg",
        )

        # General fallback
        self.assertEqual(
            get_file_extension("https://example.com/stream/123"),
            "bin",
        )

    @unittest.mock.patch("urllib.request.urlopen")
    def test_fetch_tweet_data_vxtwitter_success(self, mock_urlopen):
        """Tests that fetch_tweet_data successfully gets and normalizes vxTwitter data."""
        # Mock vxTwitter response
        vx_json = {
            "user_screen_name": "test_user",
            "date": "Wed Oct 05 18:40:30 +0000 2022",
            "likes": 10,
            "retweets": 5,
            "replies": 2,
            "text": "Hello world #test",
            "mediaURLs": ["https://pbs.twimg.com/media/FeU5fhPXkCoZXZB.jpg"],
            "media_extended": [
                {
                    "type": "image",
                    "url": "https://pbs.twimg.com/media/FeU5fhPXkCoZXZB.jpg"
                }
            ]
        }
        mock_response = unittest.mock.MagicMock()
        mock_response.read.return_value = json.dumps(vx_json).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        # Execute
        from x_downloader import fetch_tweet_data
        data = fetch_tweet_data("test_user", "123")

        # Verify
        self.assertEqual(data["username"], "test_user")
        self.assertEqual(data["text"], "Hello world #test")
        self.assertEqual(len(data["media"]), 1)
        self.assertEqual(data["media"][0]["url"], "https://pbs.twimg.com/media/FeU5fhPXkCoZXZB.jpg")
        self.assertEqual(data["media"][0]["type"], "image")

    @unittest.mock.patch("urllib.request.urlopen")
    def test_fetch_tweet_data_fallback_to_fxtwitter(self, mock_urlopen):
        """Tests that fetch_tweet_data falls back to FxTwitter when vxTwitter returns HTML."""
        import json
        # First call (vxTwitter) returns HTML redirection page
        mock_response_vx = unittest.mock.MagicMock()
        mock_response_vx.read.return_value = b"<!DOCTYPE html><html>Redirect</html>"
        mock_response_vx.__enter__.return_value = mock_response_vx

        # Second call (FxTwitter) returns JSON
        fx_json = {
            "code": 200,
            "message": "OK",
            "tweet": {
                "text": "Hello world from fx",
                "created_at": "Sun Jul 17 09:35:58 +0000 2022",
                "author": {
                    "screen_name": "fx_user"
                },
                "likes": 20,
                "retweets": 8,
                "replies": 4,
                "media": {
                    "photos": [
                        {"url": "https://pbs.twimg.com/media/photo.jpg"}
                    ],
                    "videos": [
                        {"url": "https://video.twimg.com/video.mp4"}
                    ]
                }
            }
        }
        mock_response_fx = unittest.mock.MagicMock()
        mock_response_fx.read.return_value = json.dumps(fx_json).encode("utf-8")
        mock_response_fx.__enter__.return_value = mock_response_fx

        # Set side_effect to return vx response first, then fx response
        mock_urlopen.side_effect = [mock_response_vx, mock_response_fx]

        # Execute
        from x_downloader import fetch_tweet_data
        data = fetch_tweet_data("fx_user", "123")

        # Verify
        self.assertEqual(data["username"], "fx_user")
        self.assertEqual(data["text"], "Hello world from fx")
        self.assertEqual(len(data["media"]), 2)
        self.assertEqual(data["media"][0]["type"], "image")
        self.assertEqual(data["media"][1]["type"], "video")

    @unittest.mock.patch("urllib.request.urlopen")
    def test_fetch_tweet_data_all_fail(self, mock_urlopen):
        """Tests that fetch_tweet_data raises RuntimeError if both APIs fail."""
        import urllib.error
        # Both return HTTP error or similar
        mock_urlopen.side_effect = urllib.error.HTTPError("http://api.invalid", 404, "Not Found", None, None)

        from x_downloader import fetch_tweet_data
        with self.assertRaises(RuntimeError):
            fetch_tweet_data("user", "123")

    def test_extract_urls_from_text(self):
        """Tests that X/Twitter status URLs are correctly scanned and extracted from a text block."""
        from batch_downloader import extract_urls_from_text
        text = (
            "Hey look at this: https://x.com/jack/status/20\n"
            "And here is another one (with query parameters): https://twitter.com/NASA/status/1642878772370833408?s=20&t=xyz\n"
            "This is a duplicate that should be ignored: https://x.com/jack/status/20/\n"
            "Here is fixupx link: https://fixupx.com/some_user/status/11111111\n"
            "Here is fxtwitter link: https://fxtwitter.com/other_user/status/22222222\n"
            "Some non-status links that should be ignored:\n"
            "- https://x.com/home\n"
            "- https://google.com/search\n"
        )
        expected = [
            "https://x.com/jack/status/20",
            "https://twitter.com/NASA/status/1642878772370833408?s=20&t=xyz",
            "https://fixupx.com/some_user/status/11111111",
            "https://fxtwitter.com/other_user/status/22222222",
        ]
        self.assertEqual(extract_urls_from_text(text), expected)


if __name__ == "__main__":
    unittest.main()
