#!/usr/bin/env python3
"""
batch_downloader.py

A command-line tool that parses X.com (Twitter) status URLs from a text file
and downloads their attached media files by leveraging x_downloader.py.
"""

import argparse
import logging
import os
import re
import sys
from typing import List

# Import core functionalities from x_downloader
import x_downloader

# Regex pattern to match X.com/Twitter.com status URLs (with optional query parameters)
STATUS_URL_PATTERN = re.compile(
    r"https?://(?:[a-zA-Z0-9-]+\.)*(?:x\.com|twitter\.com|fixupx\.com|fxtwitter\.com)/[^/\s]+/status/\d+(?:\?[^\s]*)?"
)


def extract_urls_from_text(text: str) -> List[str]:
    """Scans the input text and extracts all unique X.com/Twitter status URLs.

    Order of URLs is preserved.

    Args:
        text: The raw input string to scan.

    Returns:
        A list of extracted, unique status URLs.
    """
    matches = STATUS_URL_PATTERN.findall(text)
    unique_urls = []
    seen = set()

    for url in matches:
        # Normalize the URL (strip outer whitespaces and trailing slashes)
        normalized = url.strip().rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            unique_urls.append(normalized)

    return unique_urls


def process_batch(file_path: str, output_dir: str) -> bool:
    """Reads a file, extracts status URLs, and processes them one by one.

    Args:
        file_path: Path to the text file containing URLs.
        output_dir: Local directory where downloaded media will be saved.

    Returns:
        True if all detected URLs were successfully downloaded, False otherwise.
    """
    logging.info("Reading URL list from file: %s", file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        logging.error("Input file not found: %s", file_path)
        return False
    except Exception as exc:
        logging.error("Failed to read input file: %s", exc)
        return False

    urls = extract_urls_from_text(content)
    total_urls = len(urls)

    if total_urls == 0:
        logging.info("No X.com or Twitter status URLs detected in the file.")
        return True

    logging.info("Found %d unique X.com/Twitter status URLs to process.", total_urls)

    success_count = 0
    failures = []

    for idx, url in enumerate(urls, 1):
        logging.info("[%d/%d] Processing URL: %s", idx, total_urls, url)
        try:
            # We call process_tweet with dump_json=False to get standard outputs
            result = x_downloader.process_tweet(url, output_dir, dump_json=False)
            if result is not None:
                success_count += 1
                logging.info("[%d/%d] SUCCESS: Completed URL.", idx, total_urls)
            else:
                failures.append(url)
                logging.error("[%d/%d] FAILED: Could not process URL.", idx, total_urls)
        except Exception as exc:
            failures.append(url)
            logging.error("[%d/%d] EXCEPTION: Error processing URL: %s", idx, total_urls, exc)

    # Output a summary report to logging
    logging.info("=" * 60)
    logging.info("BATCH DOWNLOAD SUMMARY")
    logging.info("=" * 60)
    logging.info(f"Total URLs processed: {total_urls}")
    logging.info(f"Successful downloads: {success_count}")
    logging.info(f"Failed downloads:     {len(failures)}")

    if failures:
        logging.error("Failed URLs:")
        for fail_url in failures:
            logging.error(f"  - {fail_url}")
    logging.info("=" * 60)

    return len(failures) == 0


def main() -> None:
    """CLI Entrypoint for the batch downloader."""
    parser = argparse.ArgumentParser(
        description="Extract and download media from a batch list of X.com/Twitter URLs in a file."
    )
    parser.add_argument(
        "file",
        help="Path to the text file containing the X/Twitter status URLs.",
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

    # Re-use setup_logging from x_downloader
    x_downloader.setup_logging(args.verbose)

    success = process_batch(args.file, args.output_dir)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
