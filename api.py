#!/usr/bin/env python3
"""
api.py

A Flask API wrapper around x_downloader.py.
Exposes a POST /download endpoint that accepts a JSON payload:
    {"url": "https://x.com/username/status/12345"}
And streams the corresponding MP4 video back as application/octet-stream.
"""

import urllib.request
import logging
import sys
from flask import Flask, request, Response, jsonify
from werkzeug.exceptions import HTTPException
from x_downloader import (
    extract_tweet_info,
    fetch_tweet_data,
    sanitize_filename,
    get_file_extension,
    HTTP_HEADERS
)

app = Flask(__name__)

# Configure logging to match Flask server output and guidance
logging.basicConfig(
    level=logging.INFO,
    force=True,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    logger.error(f"Unhandled Exception: {e}", exc_info=True)
    return jsonify({"error_message": "An unexpected Internal Server Error occurred."}), 500

@app.route("/download", methods=["POST"])
def download_video():
    """
    POST /download
    Request JSON body:
        { "url": "https://x.com/username/status/12345" }
    
    Returns:
        - MP4 video file as octet-stream with filename in Content-Disposition header.
        - JSON response with error_message on failure.
    """
    if not request.is_json:
        return jsonify({"error_message": "Request must have Content-Type: application/json"}), 400

    data = request.get_json()
    if data is None:
        return jsonify({"error_message": "Request body cannot be empty"}), 400

    url = data.get("url")
    if not url:
        return jsonify({"error_message": "Missing 'url' parameter in JSON body"}), 400

    # Extract username and status ID from url
    try:
        username, status_id = extract_tweet_info(url)
    except ValueError as val_err:
        return jsonify({"error_message": f"Invalid input URL: {val_err}"}), 400
    except Exception as exc:
        return jsonify({"error_message": f"Error parsing URL: {exc}"}), 400

    # Fetch tweet metadata
    try:
        tweet_data = fetch_tweet_data(username, status_id)
    except Exception as exc:
        return jsonify({"error_message": f"Error fetching tweet metadata: {exc}"}), 500

    if not tweet_data:
        return jsonify({"error_message": "Failed to fetch tweet metadata (empty response)"}), 500

    # Find the video media item
    media_list = tweet_data.get("media", [])
    video_item = None
    for m in media_list:
        if m.get("type") == "video":
            video_item = m
            break

    if not video_item or not video_item.get("url"):
        return jsonify({"error_message": "No video media found in this post"}), 400

    video_url = video_item["url"]
    tweet_text = tweet_data.get("text", "")
    filename_base = sanitize_filename(username, tweet_text)
    ext = get_file_extension(video_url, "video")
    dest_filename = f"{filename_base}.{ext}"

    # Open connection to the remote video source
    req = urllib.request.Request(video_url, headers=HTTP_HEADERS)
    try:
        remote_resp = urllib.request.urlopen(req, timeout=30)
    except Exception as exc:
        return jsonify({"error_message": f"Failed to connect to video source URL: {exc}"}), 502

    # Forward headers and stream response
    content_length = remote_resp.headers.get("Content-Length")
    
    def generate():
        try:
            while True:
                chunk = remote_resp.read(16384)  # Stream in 16KB blocks
                if not chunk:
                    break
                yield chunk
        except Exception as exc:
            app.logger.error("Error occurred while streaming the video file: %s", exc)
        finally:
            remote_resp.close()

    headers = {
        "Content-Disposition": f'attachment; filename="{dest_filename}"',
        "Content-Type": "application/octet-stream"
    }
    if content_length:
        headers["Content-Length"] = content_length

    return Response(generate(), headers=headers)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--dev":
        logger.info("Starting Flask development server (Werkzeug)...")
        app.run(host="0.0.0.0", port=5000, debug=True)
    else:
        logger.info("Starting Waitress production server...")
        try:
            from waitress import serve
            serve(app, host="0.0.0.0", port=5000)
        except ImportError:
            logger.error("Waitress is not installed. Please run: pip install waitress")
            sys.exit(1)
