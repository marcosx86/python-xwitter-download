#!/usr/bin/env python3
"""
x_downloader.py

A command-line interface (CLI) tool written in Python to fetch metadata from X.com (formerly Twitter)
posts and download their attached media files using the unofficial `vxtwitter` API.

This script runs out-of-the-box using the Python Standard Library.
"""

import argparse
import contextlib
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

# Configure standard headers for urllib requests to mimic a browser.
# This helps avoid blocking or basic rate-limit triggers.
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def setup_logging(verbose: bool) -> None:
    """Configures the logging facility to write output to stderr.

    Using stderr ensures stdout can be cleanly piped or redirected (e.g., to a JSON file).

    Args:
        verbose: If True, set the logging level to DEBUG. Otherwise, set to INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # Clear any existing handlers to prevent duplicate logging
    root_logger.handlers = []
    root_logger.addHandler(handler)


class Profiler:
    def __init__(self):
        self.points = []

    @contextlib.contextmanager
    def step(self, name):
        start = time.perf_counter()
        try:
            yield
        finally:
            end = time.perf_counter()
            self.points.append({
                "label": name,
                "duration_ms": round((end - start) * 1000, 2)
            })


def extract_tweet_info(url: str) -> tuple[str, str]:
    """Extracts username and status ID from a standard X.com or Twitter.com status URL.

    Args:
        url: The original post URL from X/Twitter.

    Returns:
        A tuple of (username, status_id).

    Raises:
        ValueError: If the input URL is not a valid X/Twitter status link.
    """
    logging.debug("Parsing and validating URL: %s", url)
    parsed = urllib.parse.urlparse(url)

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://")

    # Match common X/Twitter domains
    domain = parsed.netloc.lower()
    if not any(
        d in domain
        for d in ("x.com", "twitter.com", "fixupx.com", "fxtwitter.com")
    ):
        raise ValueError(
            "URL domain must be x.com, twitter.com, fixupx.com, or fxtwitter.com"
        )

    # Path pattern: /<username>/status/<tweet_id>
    # Also handles trailing slashes or subpaths
    match = re.search(r"/([^/]+)/status/(\d+)", parsed.path)
    if not match:
        raise ValueError(
            "URL does not contain a valid status ID pattern (e.g., /username/status/12345)"
        )

    username = match.group(1)
    status_id = match.group(2)
    return username, status_id


def sanitize_filename(username: str, tweet_text: str) -> str:
    """Generates a sanitized base filename using the format USERNAME_FIRSTLINE.

    The first line is stripped of hashtags, limited to 10 words, and sanitized
    to only allow alphanumeric characters and underscores.

    Args:
        username: The screen name of the user who posted the tweet.
        tweet_text: The full text of the tweet.

    Returns:
        A sanitized string safe for use as a filename.
    """
    # 1. Get the first line of the tweet
    first_line = tweet_text.splitlines()[0] if tweet_text else ""

    # 2. Strip hashtags (matches '#' followed by word characters)
    first_line_no_hash = re.sub(r"#\w+", "", first_line)

    # 3. Limit to the first 10 words
    words = first_line_no_hash.split()
    limited_words = words[:10]
    joined_words = " ".join(limited_words)

    # 4. Construct base filename: <username>_<first_line_words>
    base_name = f"{username}_{joined_words}"

    # 5. Sanitize: Replace any sequence of non-alphanumeric chars with a single underscore
    sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", base_name)

    # Collapse consecutive underscores and remove leading/trailing ones
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")

    # Fallback to username only if everything else was sanitized away
    if not sanitized or sanitized == username:
        sanitized = f"{username}_tweet"

    logging.debug(
        "Sanitized filename base: %s (from text: %r)",
        sanitized,
        first_line,
    )
    return sanitized


def get_highest_quality_image_url(url: str) -> str:
    """Rewrites Twitter image URLs to request the original high-resolution image format.

    Args:
        url: The media URL.

    Returns:
        The updated URL targeting the 'orig' version if applicable, otherwise the original URL.
    """
    parsed = urllib.parse.urlparse(url)
    # Check if the domain matches Twitter's media hosts
    if "pbs.twimg.com" in parsed.netloc:
        query = urllib.parse.parse_qs(parsed.query)
        # If parameters like format or name are present, set name to orig
        if "name" in query or "format" in query:
            query["name"] = ["orig"]
            new_query = urllib.parse.urlencode(query, doseq=True)
            new_url = urllib.parse.urlunparse(parsed._replace(query=new_query))
            logging.debug("Upgraded image URL to original quality: %s", new_url)
            return new_url
        else:
            # If no parameters (e.g. direct jpg link), append name=orig as a query parameter
            new_url = urllib.parse.urlunparse(parsed._replace(query="name=orig"))
            logging.debug("Appended name=orig to image URL: %s", new_url)
            return new_url
    return url


def normalize_vxtwitter(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalizes the vxTwitter API response structure to a standardized format.

    Args:
        data: The raw JSON dictionary returned by vxTwitter API.

    Returns:
        A standardized dictionary of tweet details.
    """
    media_list = []
    media_extended = data.get("media_extended", [])
    if not media_extended and data.get("mediaURLs"):
        media_extended = [{"url": u, "type": "unknown"} for u in data.get("mediaURLs", [])]

    for item in media_extended:
        url = item.get("url")
        if not url:
            continue
        m_type = item.get("type", "unknown")
        # Standardize type to 'image', 'video', or 'unknown'
        if m_type == "image" or url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            std_type = "image"
        elif m_type in ("video", "gif") or url.lower().endswith((".mp4", ".mov", ".gif")):
            std_type = "video"
        else:
            std_type = "unknown"
        media_list.append({"url": url, "type": std_type})

    return {
        "username": data.get("user_screen_name", "user"),
        "date": data.get("date", "Unknown"),
        "likes": data.get("likes", 0),
        "retweets": data.get("retweets", 0),
        "replies": data.get("replies", 0),
        "text": data.get("text", ""),
        "media": media_list,
        "raw": data,
    }


def normalize_fxtwitter(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalizes the FxTwitter API response structure to a standardized format.

    Args:
        data: The raw JSON dictionary returned by FxTwitter API.

    Returns:
        A standardized dictionary of tweet details.
    """
    tweet = data.get("tweet", {})
    author = tweet.get("author", {})

    media_list = []
    media_data = tweet.get("media", {})

    # Photos
    for photo in media_data.get("photos", []):
        url = photo.get("url")
        if url:
            media_list.append({"url": url, "type": "image"})

    # Videos
    for video in media_data.get("videos", []):
        url = video.get("url")
        if url:
            media_list.append({"url": url, "type": "video"})

    return {
        "username": author.get("screen_name", "user"),
        "date": tweet.get("created_at", "Unknown"),
        "likes": tweet.get("likes", 0),
        "retweets": tweet.get("retweets", 0),
        "replies": tweet.get("replies", 0),
        "text": tweet.get("text", ""),
        "media": media_list,
        "raw": data,
    }


def fetch_tweet_data(username: str, status_id: str) -> Dict[str, Any]:
    """Fetches tweet/status metadata using public endpoints (vxTwitter, falling back to FxTwitter).

    Args:
        username: The screen name of the tweet author.
        status_id: The numerical status/tweet ID.

    Returns:
        A dictionary containing the standardized tweet metadata.

    Raises:
        urllib.error.URLError: If the requests fail.
        RuntimeError: If both APIs fail to return JSON.
    """
    vxtwitter_url = f"https://api.vxtwitter.com/{username}/status/{status_id}"
    logging.info("Fetching metadata from vxTwitter API...")
    try:
        req = urllib.request.Request(vxtwitter_url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as response:
            content = response.read().decode("utf-8")
            if content.strip().startswith("<!DOCTYPE html>") or "<html" in content:
                raise ValueError("Received HTML error/redirect page instead of JSON.")
            data = json.loads(content)
            logging.info("Successfully fetched data from vxTwitter.")
            return normalize_vxtwitter(data)
    except Exception as exc:
        logging.warning("vxTwitter request failed or returned invalid data: %s", exc)

    fxtwitter_url = f"https://api.fxtwitter.com/{username}/status/{status_id}"
    logging.info("Falling back: fetching metadata from FxTwitter API...")
    try:
        req = urllib.request.Request(fxtwitter_url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as response:
            content = response.read().decode("utf-8")
            if content.strip().startswith("<!DOCTYPE html>") or "<html" in content:
                raise ValueError("Received HTML error page instead of JSON.")
            data = json.loads(content)
            if data.get("code") and data.get("code") != 200:
                raise ValueError(f"FxTwitter API error code {data.get('code')}: {data.get('message')}")
            logging.info("Successfully fetched data from FxTwitter.")
            return normalize_fxtwitter(data)
    except Exception as exc:
        logging.error("FxTwitter request failed or returned invalid data: %s", exc)
        raise RuntimeError("Both vxTwitter and FxTwitter APIs failed to retrieve the tweet.")


def download_file(url: str, dest_path: str) -> None:
    """Downloads a file from a URL and saves it to the specified destination path.

    Args:
        url: The URL of the file to download.
        dest_path: The local path where the file will be saved.
    """
    logging.info("Downloading media: %s -> %s", url, dest_path)
    req = urllib.request.Request(url, headers=HTTP_HEADERS)

    # Read block-by-block to show logging output for larger downloads
    with urllib.request.urlopen(req, timeout=30) as response:
        with open(dest_path, "wb") as out_file:
            block_size = 8192
            bytes_downloaded = 0
            while True:
                buffer = response.read(block_size)
                if not buffer:
                    break
                out_file.write(buffer)
                bytes_downloaded += len(buffer)

    logging.debug("Download completed. Saved %d bytes.", bytes_downloaded)


def get_file_extension(url: str, media_type: Optional[str] = None) -> str:
    """Extracts the file extension from a URL or media type.

    Args:
        url: The media URL.
        media_type: The type of media (e.g. 'image', 'video', 'gif') if available.

    Returns:
        A string representing the file extension (e.g., 'mp4', 'jpg').
    """
    parsed = urllib.parse.urlparse(url)
    path = parsed.path

    # Attempt to grab the extension from the path
    _, ext = os.path.splitext(path)
    if ext:
        # Strip the leading dot and remove any query parameters
        return ext.lstrip(".").lower()

    # Look inside query parameters if format is specified
    query = urllib.parse.parse_qs(parsed.query)
    if "format" in query:
        return query["format"][0].lower()

    # Fallbacks based on media type
    if media_type == "video":
        return "mp4"
    elif media_type == "image":
        return "jpg"

    return "bin"


def process_tweet(
    url: str, output_dir: str, dump_json: bool
) -> Optional[Dict[str, Any]]:
    """Coordinates fetching status details, printing to stdout, and downloading media files.

    Args:
        url: The original X.com or Twitter status URL.
        output_dir: The directory where media files will be saved.
        dump_json: If True, output raw API JSON to stdout instead of formatted text.

    Returns:
        The fetched tweet data dictionary (standardized), or None if an error occurred.
    """
    profiler = Profiler()
    try:
        username, status_id = extract_tweet_info(url)
        with profiler.step("fetch_tweet_data"):
            tweet_data = fetch_tweet_data(username, status_id)
    except ValueError as val_err:
        logging.error("Invalid input: %s", val_err)
        return None
    except urllib.error.HTTPError as http_err:
        logging.error(
            "HTTP error occurred while fetching metadata: %s %s",
            http_err.code,
            http_err.reason,
        )
        return None
    except urllib.error.URLError as url_err:
        logging.error("Network connection error: %s", url_err.reason)
        return None
    except json.JSONDecodeError:
        logging.error("Failed to parse JSON response from the API server.")
        return None
    except Exception as exc:
        logging.error("An error occurred: %s", exc)
        return None

    # Print metadata to stdout
    if dump_json:
        # Print raw original JSON directly to stdout
        print(json.dumps(tweet_data.get("raw"), indent=2))
    else:
        # Print human-readable textual output
        print("=" * 60)
        print(f"User: @{tweet_data.get('username', 'Unknown')}")
        print(f"Date: {tweet_data.get('date', 'Unknown')}")
        print(
            f"Stats: {tweet_data.get('likes', 0)} Likes | "
            f"{tweet_data.get('retweets', 0)} Retweets | "
            f"{tweet_data.get('replies', 0)} Replies"
        )
        print("-" * 60)
        print(tweet_data.get("text", ""))
        print("=" * 60)
        media_list = tweet_data.get("media", [])
        if media_list:
            print("Media URLs:")
            for m in media_list:
                print(f"  - {m.get('url')}")
            print("=" * 60)

    # Process media downloads
    media_list = tweet_data.get("media", [])

    if not media_list:
        logging.info("No media files found in this post.")
        return tweet_data

    # Ensure output directory exists
    if not os.path.exists(output_dir):
        logging.info("Creating directory: %s", output_dir)
        os.makedirs(output_dir, exist_ok=True)

    username = tweet_data.get("username", "user")
    tweet_text = tweet_data.get("text", "")
    filename_base = sanitize_filename(username, tweet_text)

    for idx, media_item in enumerate(media_list):
        original_url = media_item.get("url")
        media_type = media_item.get("type", "unknown")

        if not original_url:
            continue

        # Adjust quality for images
        if media_type == "image" or original_url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        ):
            download_url = get_highest_quality_image_url(original_url)
        else:
            download_url = original_url

        ext = get_file_extension(download_url, media_type)

        # Append suffix if there are multiple media items
        if len(media_list) > 1:
            dest_filename = f"{filename_base}_{idx + 1}.{ext}"
        else:
            dest_filename = f"{filename_base}.{ext}"

        dest_path = os.path.join(output_dir, dest_filename)

        try:
            with profiler.step(f"download_media_{idx+1}"):
                download_file(download_url, dest_path)
            logging.info("Successfully downloaded: %s", dest_filename)
        except Exception as dl_err:
            logging.error(
                "Failed to download media item %d (%s): %s",
                idx + 1,
                download_url,
                dl_err,
            )

    tweet_data["flame_graph"] = profiler.points
    return tweet_data


def main() -> None:
    """Entrypoint of the script. Handles argument parsing and execution control."""
    parser = argparse.ArgumentParser(
        description="Fetch X.com / Twitter status details and download its media files."
    )
    parser.add_argument(
        "url",
        help="The URL of the X.com / Twitter status (e.g. https://x.com/username/status/123456789)",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Dump the raw API JSON output to stdout instead of formatted text",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=".",
        help="The directory to save downloaded media files (default: current directory)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show verbose/debug logging output in stderr",
    )

    args = parser.parse_args()

    # Set up stderr logging
    setup_logging(args.verbose)

    # Process and fetch the tweet
    result = process_tweet(args.url, args.output_dir, args.json)

    # Exit with code 1 if execution failed
    if result is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
