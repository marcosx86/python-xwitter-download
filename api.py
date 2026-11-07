#!/usr/bin/env python3
"""
api.py

A Flask API wrapper around x_downloader.py.
Exposes endpoints:
    - POST /download: Accepts a JSON payload {"url": "...", "index": 1 (optional)}
      Streams a single file or a ZIP bundle if multiple media items exist.
    - GET /tweet: Accepts a 'url' query parameter and returns tweet details as JSON.
"""

import json
import logging
import sys
import tempfile
import urllib.request
import zipfile
from flask import Flask, request, Response, jsonify
from werkzeug.exceptions import HTTPException
from x_downloader import (
    extract_tweet_info,
    fetch_tweet_data,
    sanitize_filename,
    get_file_extension,
    get_highest_quality_image_url,
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

def build_tweet_payload(tweet_data, username, status_id):
    """Builds the textual tweet payload shared by GET /tweet and the ZIP metadata file."""
    return {
        "username": tweet_data.get("username", username),
        "status_id": status_id,
        "content": tweet_data.get("text", ""),
        "text": tweet_data.get("text", ""),
        "date": tweet_data.get("date", "Unknown"),
        "likes": tweet_data.get("likes", 0),
        "retweets": tweet_data.get("retweets", 0),
        "replies": tweet_data.get("replies", 0),
        "media": tweet_data.get("media", [])
    }


@app.route("/tweet", methods=["GET"])
def get_tweet():
    """
    GET /tweet?url=https://x.com/username/status/12345
    
    Returns:
        JSON response with tweet details: username, text/content, date, metrics, and media.
    """
    url = request.args.get("url")
    if not url:
        return jsonify({"error_message": "Missing 'url' query parameter"}), 400

    try:
        username, status_id = extract_tweet_info(url)
    except ValueError as val_err:
        return jsonify({"error_message": f"Invalid input URL: {val_err}"}), 400
    except Exception as exc:
        return jsonify({"error_message": f"Error parsing URL: {exc}"}), 400

    try:
        tweet_data = fetch_tweet_data(username, status_id)
    except Exception as exc:
        return jsonify({"error_message": f"Error fetching tweet metadata: {exc}"}), 500

    if not tweet_data:
        return jsonify({"error_message": "Failed to fetch tweet metadata (empty response)"}), 500

    return jsonify(build_tweet_payload(tweet_data, username, status_id)), 200


@app.route("/download", methods=["POST"])
def download_media():
    """
    POST /download
    Request JSON body:
        {
            "url": "https://x.com/username/status/12345",
            "index": 1  # Optional: 1-based index to download a specific media file
        }
    
    Returns:
        - If 'index' is provided or only 1 media item exists: single media file stream.
        - If multiple media items exist and no 'index' is provided: a ZIP archive containing all media files.
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

    target_index = data.get("index")
    if target_index is not None:
        try:
            target_index = int(target_index)
            if target_index < 1:
                return jsonify({"error_message": "'index' must be a positive integer starting at 1"}), 400
        except (ValueError, TypeError):
            return jsonify({"error_message": "'index' must be a valid integer"}), 400

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

    media_list = [m for m in tweet_data.get("media", []) if m.get("url")]
    if not media_list:
        return jsonify({"error_message": "No media found in this post"}), 400

    tweet_text = tweet_data.get("text", "")
    filename_base = sanitize_filename(username, tweet_text)

    # Helper function to resolve download URL and file extension for a media item
    def resolve_media_info(media_item):
        m_url = media_item["url"]
        m_type = media_item.get("type", "unknown")
        if m_type == "image" or m_url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            dl_url = get_highest_quality_image_url(m_url)
        else:
            dl_url = m_url
        ext = get_file_extension(dl_url, m_type)
        return dl_url, ext

    # Case 1: Specific media requested by index
    if target_index is not None:
        if target_index > len(media_list):
            return jsonify({
                "error_message": f"Index {target_index} is out of range. Post contains {len(media_list)} media items."
            }), 400
        selected_media = media_list[target_index - 1]
        download_url, ext = resolve_media_info(selected_media)
        dest_filename = f"{filename_base}_{target_index}.{ext}" if len(media_list) > 1 else f"{filename_base}.{ext}"
        return _stream_single_file(download_url, dest_filename)

    # Case 2: Only 1 media item exists
    if len(media_list) == 1:
        download_url, ext = resolve_media_info(media_list[0])
        dest_filename = f"{filename_base}.{ext}"
        return _stream_single_file(download_url, dest_filename)

    # Case 3: Multiple media items and no index specified -> Bundle into a ZIP
    # Spooled temp file: kept in RAM up to 16 MB, then spilled to disk.
    zip_buffer = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    try:
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                f"{filename_base}.json",
                json.dumps(build_tweet_payload(tweet_data, username, status_id), indent=2, ensure_ascii=False)
            )
            for idx, media_item in enumerate(media_list, start=1):
                download_url, ext = resolve_media_info(media_item)
                item_filename = f"{filename_base}_{idx}.{ext}"
                req = urllib.request.Request(download_url, headers=HTTP_HEADERS)
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        with zf.open(item_filename, mode="w", force_zip64=True) as dest:
                            while True:
                                chunk = resp.read(16384)
                                if not chunk:
                                    break
                                dest.write(chunk)
                except Exception as exc:
                    zip_buffer.close()
                    return jsonify({"error_message": f"Failed to download media item {idx} ({download_url}): {exc}"}), 502
    except Exception:
        zip_buffer.close()
        raise

    size = zip_buffer.tell()
    zip_buffer.seek(0)

    def generate_zip():
        try:
            while True:
                chunk = zip_buffer.read(16384)
                if not chunk:
                    break
                yield chunk
        finally:
            zip_buffer.close()

    zip_filename = f"{filename_base}.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{zip_filename}"',
        "Content-Type": "application/zip",
        "Content-Length": str(size)
    }
    return Response(generate_zip(), headers=headers)


def _stream_single_file(download_url: str, dest_filename: str):
    """Opens a connection to download_url and streams the response."""
    req = urllib.request.Request(download_url, headers=HTTP_HEADERS)
    try:
        remote_resp = urllib.request.urlopen(req, timeout=30)
    except Exception as exc:
        return jsonify({"error_message": f"Failed to connect to media source URL: {exc}"}), 502

    content_length = remote_resp.headers.get("Content-Length")

    def generate():
        try:
            while True:
                chunk = remote_resp.read(16384)  # Stream in 16KB blocks
                if not chunk:
                    break
                yield chunk
        except Exception as exc:
            app.logger.error("Error occurred while streaming the media file: %s", exc)
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
