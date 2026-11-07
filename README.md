# X/Twitter Post Media Downloader

A lightweight, zero-dependency Python command-line utility to fetch post/status metadata from X (formerly Twitter) and download attached media files in high resolution.

## Features

- **No API Keys or Auth Required**: Utilizes the public `vxtwitter` API endpoint to query status metadata.
- **Zero External Dependencies**: Implemented strictly using the Python standard library (`urllib`, `argparse`, `logging`, `json`, `re`).
- **High-Quality Media Downloads**: Automatically rewrites image URLs to fetch the original resolution (`name=orig`) and captures raw video files.
- **Sanitized Naming Scheme**: Generates human-readable, safe file names using the format: `<username>_<first_line_of_tweet>.<extension>`
  - First line is extracted from the tweet.
  - All hashtags (e.g. `#coding`) are stripped.
  - Length is capped at 10 words.
  - Unsafe characters are sanitized and replaced with a single underscore.
- **Pipelining-Friendly**: Logs and status indicators are directed to `stderr`, leaving `stdout` perfectly clean for piping or redirection to files.
- **Flask Web API**: Includes an optional `api.py` wrapper to run the downloader as a REST service.
- **Docker Ready**: Shipped with a `Dockerfile` and automated GitHub Actions publishing workflow.
- **Built-in Profiling**: Included profiler for tracking download speeds and extraction times.

---

## Requirements

- **Python 3.6+** (tested and fully compatible with Python 3.12)
- Active internet connection.

---

## Installation

Simply download the `x_downloader.py` script:

```bash
git clone https://github.com/yourusername/python-xwitter-download.git
cd python-xwitter-download
```

Or just copy `x_downloader.py` into your working folder.

---

## Usage

Run the script by passing the target X/Twitter URL:

```bash
python x_downloader.py <X_POST_URL> [flags]
```

### Command Line Arguments

| Argument | Short Flag | Description |
| :--- | :--- | :--- |
| `url` | *None* | **(Required)** The status URL from `x.com`, `twitter.com`, `fixupx.com`, or `fxtwitter.com`. |
| `--json` | `-j` | Dumps the raw API response (JSON) directly to `stdout` instead of the human-readable text block. |
| `--output-dir` | `-o` | The folder where the media files will be saved (defaults to current directory `.`). |
| `--verbose` | `-v` | Enables debug logging on `stderr` for detail on URLs, quality upgrading, and request headers. |

---

## Examples

### 1. Basic Metadata Extraction and Media Download
Fetch a tweet and save any attached media to the current directory:
```bash
python x_downloader.py https://x.com/Twitter/status/1577730467436138524
```

*Output (stdout):*
```text
============================================================
User: @Twitter
Date: Wed Oct 05 18:40:30 +0000 2022
Stats: 21664 Likes | 3229 Retweets | 2911 Replies
------------------------------------------------------------
Example tweet text content
============================================================
Media URLs:
  - https://pbs.twimg.com/media/FeU5fhPXkCoZXZB.jpg
============================================================
```
*Logs (stderr):*
```text
[2026-06-11 13:00:00] INFO: Fetching metadata from API...
[2026-06-11 13:00:01] INFO: Downloading media: https://pbs.twimg.com/media/FeU5fhPXkCoZXZB.jpg?name=orig -> ./Twitter_Example_tweet_text_content.jpg
[2026-06-11 13:00:02] INFO: Successfully downloaded: Twitter_Example_tweet_text_content.jpg
```

### 2. Redirect Metadata to a File (Stdout separation)
Save only the human-readable text details to a text file while still showing logging details in the terminal:
```bash
python x_downloader.py https://x.com/Twitter/status/1577730467436138524 > metadata.txt
```

### 3. Dump Raw API JSON and Save Media to a Specific Folder
Export raw JSON data and direct downloads to a folder named `downloads/`:
```bash
python x_downloader.py https://x.com/Twitter/status/1577730467436138524 --json --output-dir downloads
```

---

## Batch Downloading

You can download media from a list of X.com/Twitter URLs stored in a text file using `batch_downloader.py`.

The batch downloader parses the input file, automatically extracts any valid status URLs using a regular expression, and downloads their media. It handles failures gracefully by logging them and continuing to process the remaining URLs.

### Usage

```bash
python batch_downloader.py <PATH_TO_URLS_FILE> [flags]
```

### CLI Arguments

| Argument | Short Flag | Description |
| :--- | :--- | :--- |
| `file` | *None* | **(Required)** Path to the text file containing X/Twitter URLs. |
| `--output-dir` | `-o` | The folder where the media files will be saved (default: `.`). |
| `--verbose` | `-v` | Enables debug logging on `stderr`. |

### Example

1. Create a text file `urls.txt` with X/Twitter URLs (comments or other text can be mixed in):
   ```text
   # Let's download this first
   https://x.com/jack/status/20
   
   # And this video
   https://x.com/UnslothAI/status/2065433326706684135
   ```
2. Run the batch downloader script:
   ```bash
   python batch_downloader.py urls.txt --output-dir media_files
   ```

---

## Running Unit Tests

Run the test suite to verify the URL parsing, filename sanitization, high-quality rewriting, and batch extraction logic:

```bash
python -m unittest test_x_downloader.py
python -m unittest test_api.py
```

---

## Web API & Docker

You can run `x_downloader` as a REST API that streams media back to the client.

### Local Setup
Install the API dependencies:
```bash
pip install -r requirements.txt
```

Run the API:
```bash
# Development (Werkzeug)
python api.py --dev

# Production (Waitress)
python api.py
```

### Docker & Docker Compose
A `Dockerfile` and `docker-compose.yml` are included to containerize and run the API easily.

**Using Docker:**
```bash
docker build -t xwitter-api .
docker run -p 5000:5000 xwitter-api
```

**Using Docker Compose:**
```bash
docker compose up --build
```
*(A GitHub Actions workflow is also included to automatically publish the Docker image.)*

### API Usage

#### **GET `/tweet`**
Fetches post details including author screen name, tweet textual content, timestamp, engagement metrics, and media links.

**Query Parameters:**
- `url` (required): Full URL to the X/Twitter post.

**Example Request:**
```bash
curl -X GET "http://localhost:5000/tweet?url=https://x.com/Twitter/status/1577730467436138524"
```

**Example Response:**
```json
{
  "username": "Twitter",
  "status_id": "1577730467436138524",
  "content": "hello literally everyone",
  "text": "hello literally everyone",
  "date": "Tue Oct 04 18:31:00 +0000 2022",
  "likes": 50000,
  "retweets": 12000,
  "replies": 8000,
  "media": []
}
```

#### **POST `/download`**
Accepts a JSON body containing the target X/Twitter URL and streams the attached media file(s).

**Multiple Media Handling (Approach 3)**:
- **Single item**: Streamed directly as a file (`application/octet-stream`).
- **Multiple items**: Bundled into a **`.zip` archive** (`application/zip`) containing all media items plus a `<name>.json` file with the same metadata as `GET /tweet`.
- **Specific item**: Provide an optional 1-based `"index"` in the request body to download a single item even if multiple exist.
- **High Quality**: Images are automatically requested in full original resolution (`name=orig`).

**Request (Download all / auto-detect):**
```json
{
  "url": "https://x.com/username/status/12345"
}
```

**Request (Download specific item):**
```json
{
  "url": "https://x.com/username/status/12345",
  "index": 2
}
```

**cURL Examples:**
```bash
# Direct file or ZIP bundle
curl -X POST http://localhost:5000/download \
     -H "Content-Type: application/json" \
     -d '{"url": "https://x.com/Twitter/status/1577730467436138524"}' \
     --output downloaded_media

# Download only item 1
curl -X POST http://localhost:5000/download \
     -H "Content-Type: application/json" \
     -d '{"url": "https://x.com/Twitter/status/1577730467436138524", "index": 1}' \
     --output item_1.jpg
```

