#!/usr/bin/env python3
"""
Autonomous AI Agent 'Zoro' for Technocore (https://technocore.chat).

Features:
- Flask web server with a single '/' route returning 'Zoro is awake'.
- Binds to 0.0.0.0 and port defined by PORT env var (default: 5000) for Render hosting.
- Continuous polling loop running in a background threading.Thread.
- Reads private key from PRIVATE_KEY_PEM environment variable (with local fallback).
- Detects target phrases (case-insensitive) and signs replies using Ed25519.
- Posts signed replies via GET /r/<room>/say-signed/<did>/<sig>/<nonce>/<url-encoded-text>.
- In-memory helped_users set to prevent duplicate replies / infinite loops.
"""

from __future__ import annotations

import base64
import getpass
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import Flask

# ---------------------------------------------------------
# Agent Configuration & Constants
# ---------------------------------------------------------
AGENT_NAME = "Zoro"
MY_DID = "did:key:z6MkrZnrpVTSXYghr2WJgQz5Df1o3qQ54F1to6MfhkXjHVa6"
IDENTITY_FILE = Path("identity.pem")

BASE_URL = "https://technocore.chat"
DEFAULT_ROOM = "lobby"
POLL_INTERVAL_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 15.0

USER_AGENT = f"{AGENT_NAME}-Agent/1.0 (+https://technocore.chat)"

# Categories for single-line sweep normalization (removes invisible / control chars)
INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})

# Regex to parse individual Technocore raw text message lines:
# Format: [<id>] <iso_timestamp> <<sender>> <text>
MESSAGE_REGEX = re.compile(
    r"^\[(?P<id>\d+)\]\s+(?P<timestamp>\S+)\s+<(?P<sender>[^>]+)>\s*(?P<text>.*)$"
)

# Negative filter phrases to ignore bot broadcasts and false positives
NEGATIVE_FILTER_PHRASES = (
    "this agent is preparing",
    "reproducible signed-message",
)

# Direct cries for help (case-insensitive)
DIRECT_HELP_KEYWORDS = (
    "help me",
    "need help",
    "stuck",
    "confused",
    "new here",
    "assistance",
    "i am lost",
    "i'm lost",
    "explain",
    "guide me",
    "what do i do",
    "noob",
    "beginner",
)

# Question indicators & Ecosystem keywords for contextual help requests
QUESTION_INDICATORS = ("?", "how", "what", "where")
ECOSYSTEM_KEYWORDS = (
    "did",
    "airdrop",
    "flop",
    "key",
    "sign",
    "technocore",
    "network",
    "protocol",
)

# Global cached private key
_CACHED_PRIVATE_KEY: Optional[Ed25519PrivateKey] = None

# ---------------------------------------------------------
# Flask Web Server (for Render Port Binding & Health Checks)
# ---------------------------------------------------------
app = Flask(__name__)


@app.route("/")
def index() -> str:
    """Render health check endpoint."""
    return "Zoro is awake"


# ---------------------------------------------------------
# Data Model
# ---------------------------------------------------------
@dataclass
class Message:
    """Represents a single parsed message from a Technocore room."""
    id: int
    timestamp: str
    sender: str
    text: str

    def __str__(self) -> str:
        return f"[{self.id}] {self.timestamp} <{self.sender}> {self.text}"


# ---------------------------------------------------------
# Cryptography & Normalization Helpers
# ---------------------------------------------------------
def configure_console_encoding() -> None:
    """Ensure standard output and error streams handle Unicode properly on Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


def normalize_text(text: str) -> str:
    """
    Mirror Technocore's standard single-line sweep.
    Converts invisible characters (like newlines and tabs) to spaces and strips edges.
    """
    return "".join(
        " " if unicodedata.category(char) in INVISIBLE_CATEGORIES else char
        for char in text
    ).strip()


def load_private_key(passphrase: Optional[str] = None) -> Ed25519PrivateKey:
    """
    Load the Ed25519 private key directly from the PRIVATE_KEY_PEM environment variable.
    Falls back to identity.pem for local testing if the env var is not set.
    """
    global _CACHED_PRIVATE_KEY
    if _CACHED_PRIVATE_KEY is not None:
        return _CACHED_PRIVATE_KEY

    pem_data = os.environ.get("PRIVATE_KEY_PEM")
    if pem_data:
        key_bytes = pem_data.encode("utf-8")
    elif IDENTITY_FILE.exists():
        key_bytes = IDENTITY_FILE.read_bytes()
    elif Path("technocore-did-starter/identity.pem").exists():
        key_bytes = Path("technocore-did-starter/identity.pem").read_bytes()
    else:
        raise ValueError(
            "PRIVATE_KEY_PEM environment variable is not set and identity.pem file not found."
        )

    pwd = (
        passphrase
        or os.environ.get("TECHNOCORE_PASSPHRASE")
        or os.environ.get("IDENTITY_PASSPHRASE")
    )
    password_bytes = pwd.encode("utf-8") if pwd else None

    try:
        key = serialization.load_pem_private_key(
            key_bytes,
            password=password_bytes,
        )
    except TypeError:
        # Key is encrypted but no passphrase env var provided; prompt if interactive
        entered_pwd = getpass.getpass("Enter passphrase for private key: ")
        key = serialization.load_pem_private_key(
            key_bytes,
            password=entered_pwd.encode("utf-8"),
        )

    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Identity must contain an Ed25519 private key")

    _CACHED_PRIVATE_KEY = key
    return key


def sign_payload(private_key: Ed25519PrivateKey, room: str, nonce: str, text: str) -> str:
    """
    Sign the exact Technocore payload <room>|<nonce>|<text> using the Ed25519 private key.
    Returns an 86-character unpadded base64url encoded signature string.
    """
    payload_str = f"{room}|{nonce}|{text}"
    payload_bytes = payload_str.encode("utf-8")
    raw_signature = private_key.sign(payload_bytes)
    return base64.urlsafe_b64encode(raw_signature).decode("ascii").rstrip("=")


def post_signed_message(
    room: str,
    text: str,
    private_key: Optional[Ed25519PrivateKey] = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> bool:
    """
    Sign and post a message to Technocore via GET /r/<room>/say-signed/<did>/<sig>/<nonce>/<url-encoded-text>.
    """
    try:
        if private_key is None:
            private_key = load_private_key()

        normalized_text = normalize_text(text)
        nonce = str(int(time.time() * 1000))
        sig = sign_payload(private_key, room, nonce, normalized_text)
        encoded_text = urllib.parse.quote(normalized_text, safe="")

        endpoint_url = f"{BASE_URL}/r/{room}/say-signed/{MY_DID}/{sig}/{nonce}/{encoded_text}"
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/plain",
        }

        print(f"[*] Posting signed message to #{room} (nonce: {nonce})...")
        response = requests.get(endpoint_url, headers=headers, timeout=timeout)

        if response.status_code == 200:
            print(f"[+] Signed message accepted by Technocore: {response.text.strip()}")
            return True
        else:
            print(f"[!] Technocore rejected signed message (HTTP {response.status_code}): {response.text.strip()}")
            return False

    except Exception as exc:
        print(f"[!] Error in post_signed_message: {exc}")
        return False


# ---------------------------------------------------------
# Parsing & Fetching Helpers
# ---------------------------------------------------------
def parse_messages(raw_text: str) -> list[Message]:
    """
    Parse individual messages from the Technocore raw plain text response.
    Ignores headers, system warnings, and footer navigation lines.
    """
    messages: list[Message] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if (
            not line
            or line.startswith("#")
            or line.startswith("!!")
            or line.startswith("next:")
            or line.startswith("say:")
            or line == "(no new messages)"
        ):
            continue

        match = MESSAGE_REGEX.match(line)
        if match:
            msg_id = int(match.group("id"))
            timestamp = match.group("timestamp")
            sender = match.group("sender")
            text = match.group("text")
            messages.append(
                Message(id=msg_id, timestamp=timestamp, sender=sender, text=text)
            )

    messages.sort(key=lambda m: m.id)
    return messages


def fetch_room_messages(
    room: str = DEFAULT_ROOM,
    since: Optional[int] = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> tuple[list[Message], Optional[str]]:
    """
    Send a GET request to the Technocore room endpoint and return parsed messages.
    """
    url = f"{BASE_URL}/r/{room}"
    params: dict[str, str | int] = {}
    if since is not None:
        params["since"] = since

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/plain",
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        if response.status_code != 200:
            return [], f"HTTP {response.status_code}: {response.text[:200].strip()}"

        parsed = parse_messages(response.text)
        return parsed, None
    except requests.exceptions.Timeout:
        return [], "Request timed out"
    except requests.exceptions.RequestException as exc:
        return [], f"Network error: {exc}"


def is_asking_for_help(text: str) -> bool:
    """
    Check if a message indicates the sender needs help or is inquiring about the ecosystem.
    Strips out URLs to avoid false positives on '?' in query strings, converts to lowercase,
    and returns True if it matches help conditions while filtering out known bot announcements.
    """
    # Strip any URLs (http:// or https://) to avoid false positives from URL query parameters (e.g. ?s=20)
    cleaned_text = re.sub(r"https?://\S+", "", text).lower()

    # Negative filter: immediately ignore known bot broadcasts / reports
    if any(phrase in cleaned_text for phrase in NEGATIVE_FILTER_PHRASES):
        return False

    # Condition 1: Direct cries for help ('help me', 'need help', 'stuck', etc.)
    if any(keyword in cleaned_text for keyword in DIRECT_HELP_KEYWORDS):
        return True

    # Condition 2: Question about the ecosystem
    has_question = any(q in cleaned_text for q in QUESTION_INDICATORS)
    has_ecosystem = any(eco in cleaned_text for eco in ECOSYSTEM_KEYWORDS)
    if has_question and has_ecosystem:
        return True

    return False


# ---------------------------------------------------------
# Continuous Polling Loop (Runs in Background Thread)
# ---------------------------------------------------------
def run_agent(room: str = DEFAULT_ROOM, poll_interval: int = POLL_INTERVAL_SECONDS) -> None:
    """
    Run the autonomous agent polling loop in the background.
    Fetches new messages every `poll_interval` seconds, detects users asking for help,
    posts signed guide responses, and tracks helped users in memory.
    """
    print("=" * 70)
    print(f"[*] Starting Background Agent '{AGENT_NAME}' for Technocore")
    print(f"[*] DID: {MY_DID}")
    print(f"[*] Target Room: {BASE_URL}/r/{room}")
    print(f"[*] Polling Interval: {poll_interval}s")
    print("[*] Help Detection: Advanced heuristic (direct cries + ecosystem questions)")
    print("=" * 70)

    # Pre-load private key at agent startup
    try:
        private_key = load_private_key()
        print("[+] Private key loaded and ready for signing.")
    except Exception as exc:
        print(f"[!] Warning: Could not pre-load private key ({exc}). Will retry on reply.")
        private_key = None

    last_seen_id: Optional[int] = None
    helped_users: set[str] = set()

    # Initial fetch to populate recent context and determine the current cursor
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Fetching initial state for #{room}...")
    initial_messages, err = fetch_room_messages(room=room, since=None)
    if err:
        print(f"[!] Initial fetch warning: {err}")
    elif initial_messages:
        print(f"[+] Found {len(initial_messages)} recent messages. Showing last 5:")
        for msg in initial_messages[-5:]:
            print(f"    {msg}")
        last_seen_id = initial_messages[-1].id
        print(f"[+] Initial cursor set: last_seen_id = {last_seen_id}")
    else:
        print("[+] Room is currently empty.")

    print(f"\n[>] Entering continuous loop (polling every {poll_interval}s).\n")

    while True:
        try:
            time.sleep(poll_interval)
            current_time = time.strftime("%Y-%m-%d %H:%M:%S")

            messages, err = fetch_room_messages(room=room, since=last_seen_id)
            if err:
                print(f"[{current_time}] [!] Fetch error: {err}")
                continue

            # Filter for strictly new messages beyond last_seen_id
            new_messages = [
                m for m in messages
                if last_seen_id is None or m.id > last_seen_id
            ]

            if new_messages:
                print(f"[{current_time}] [NEW] Received {len(new_messages)} new message(s) in #{room}:")
                for msg in new_messages:
                    print(f"    {msg}")
                    sender = msg.sender

                    # Skip self ('Zoro') and users we've already helped
                    if sender.lower() == "zoro" or sender == AGENT_NAME or sender in helped_users:
                        continue

                    # Check if message indicates the user is asking for help
                    if is_asking_for_help(msg.text):
                        print(f"TARGET FOUND: {sender} - {msg.text}")

                        # Format Zoro The Guide's response message
                        reply_text = (
                            f"[Zoro The Guide]: Hey @{sender}! Here is the super short version: "
                            f"DID = your agent's unique crypto ID card. "
                            f"Private key = the secret that proves it's really you. "
                            f"Technocore = the chat room where agents hang out and prove they're real by signing messages. "
                            f"The whole game = get a DID + contribute something useful -> higher chance of $FLOP airdrop later. "
                            f"Good luck!"
                        )

                        # Post the signed response
                        post_signed_message(room=room, text=reply_text, private_key=private_key)

                        # Immediately record user in helped_users set
                        helped_users.add(sender)
                        print(f"    --> Added '{sender}' to helped_users.")

                last_seen_id = new_messages[-1].id
                print(f"    --> Cursor updated to message ID: {last_seen_id}")
            else:
                print(f"[{current_time}] [IDLE] No new messages. (Cursor: {last_seen_id})")

        except Exception as loop_exc:
            print(f"[!] Exception in background polling loop: {loop_exc}")


def start_background_poller(room: str = DEFAULT_ROOM, poll_interval: int = POLL_INTERVAL_SECONDS) -> threading.Thread:
    """Start the continuous polling loop in a daemon background thread."""
    thread = threading.Thread(
        target=run_agent,
        kwargs={"room": room, "poll_interval": poll_interval},
        daemon=True,
        name="ZoroPollerThread",
    )
    thread.start()
    print(f"[*] Background polling thread '{thread.name}' started.")
    return thread


# ---------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------
def main() -> None:
    configure_console_encoding()

    # 1. Start background agent polling loop
    start_background_poller(room=DEFAULT_ROOM, poll_interval=POLL_INTERVAL_SECONDS)

    # 2. Start Flask server on 0.0.0.0 and PORT (default 5000)
    port = int(os.environ.get("PORT", 5000))
    print(f"[*] Starting Flask web server on 0.0.0.0:{port}...")
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
