# ⚔️ Zoro Agent for Technocore

[![Python 3.12](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Identity](https://img.shields.io/badge/Identity-Ed25519-6D28D9)](https://w3c-ccg.github.io/did-method-key/)
[![Framework](https://img.shields.io/badge/Framework-Flask-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-059669.svg)](LICENSE)

An autonomous, 24/7 Python agent built for **Flop Labs' HTTP-native [Technocore](https://technocore.chat)** chat mesh. **Zoro** acts as a friendly, intelligent onboarding guide that monitors the Technocore lobby, identifies newcomers and users who need assistance, and delivers cryptographically signed guidance while filtering out spam bots.

---

## 📖 Table of Contents
- [Overview](#-overview)
- [Key Features](#-key-features)
- [How Zoro Works](#-how-zoro-works)
- [Environment Variables](#-environment-variables)
- [Setup & Installation](#-setup--installation)
- [24/7 Cloud Deployment ($0 Budget)](#-247-cloud-deployment-0-budget)
- [Technocore Protocol Details](#-technocore-protocol-details)
- [License](#-license)

---

## 🌟 Overview

**Technocore** is an HTTP-native communication protocol and chat server designed for AI agents and decentralized identities (`did:key`). In public rooms like `#lobby`, human developers and autonomous agents interact in real time.

**Zoro The Guide** continuously polls the lobby and provides clear, actionable onboarding explanations:
- What a **DID** is (`did:key`)
- Why private keys prove identity
- How Technocore message signing works
- How agents can contribute and position themselves for potential ecosystem rewards (`$FLOP`)

---

## ⚡ Key Features

- 🧠 **Smart Intent Detection & Anti-Spam Filtering**:
  - **Direct Help Triggers**: Detects cries for help such as `"help me"`, `"need help"`, `"stuck"`, `"confused"`, `"new here"`, `"i am lost"`, `"i'm lost"`, `"guide me"`, etc.
  - **Ecosystem Inquiries**: Identifies questions combining interrogatives (`?`, `how`, `what`, `where`) with ecosystem topics (`did`, `airdrop`, `flop`, `key`, `sign`, `technocore`, `network`, `protocol`).
  - **Negative Bot Filters**: Rejects common bot broadcast patterns (e.g., `"this agent is preparing"`, `"reproducible signed-message"`) to avoid false-positive replies.
  - **URL Query Sanitization**: Strips URLs from incoming text before trigger analysis so query parameters (like `?s=20`) do not trigger accidental replies.

- 🔐 **Cryptographic Message Signing**:
  - Signs every reply using the agent's local **Ed25519** private key.
  - Computes unpadded 86-character Base64URL signatures adhering to Technocore's `/say-signed` specification.
  - Implements Technocore's standard single-line sweep to normalize invisible/control characters.

- 🛡️ **Spam & Infinite Loop Prevention**:
  - Maintains an in-memory `helped_users` set to ensure each user is only guided once per session.
  - Skips messages originating from Zoro itself to avoid recursive loops.

- ☁️ **Zero-Cost 24/7 Cloud Deployment**:
  - Integrates a lightweight **Flask** web server (`GET /`) binding to `0.0.0.0:$PORT`.
  - Runs the continuous 60-second polling worker in a background daemon thread (`threading.Thread`).
  - Compatible with free-tier serverless and container hosts (Render, Railway, Fly.io) paired with keep-alive pingers (UptimeRobot).

---

## 🔄 How Zoro Works

```text
       ┌────────────────────────────────────────────────────────┐
       │                Technocore Chat Mesh                   │
       │              (https://technocore.chat)                 │
       └──────────────┬────────────────────────▲────────────────┘
                      │ GET /r/lobby?since=N   │ GET /r/lobby/say-signed/...
                      │ (Every 60s)            │ (Signed Ed25519 response)
                      ▼                        │
       ┌───────────────────────────────────────┴────────────────┐
       │                   Zoro Agent Core                      │
       │                                                        │
       │  1. Parse messages & track last_seen_id                │
       │  2. Strip URLs & execute negative bot filters          │
       │  3. Evaluate is_asking_for_help(text)                  │
       │  4. Deduplicate via helped_users set                   │
       │  5. Sign payload: room|nonce|normalized_text           │
       └───────────────────────┬────────────────────────────────┘
                               │
                               ▼
       ┌────────────────────────────────────────────────────────┐
       │             Flask Web Server (Port 5000)               │
       │       GET /  ──► Returns "Zoro is awake"               │
       │         (Health checks & UptimeRobot pings)            │
       └────────────────────────────────────────────────────────┘
```

---

## ⚙️ Environment Variables

Configure the following environment variables on your deployment platform or in your local `.env` file:

| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `PRIVATE_KEY_PEM` | **Yes** (Cloud) | *None* | Raw PEM text of your Ed25519 private key (used instead of `identity.pem` on ephemeral cloud hosts). |
| `PYTHONUNBUFFERED` | **Recommended** | `1` | Forces standard output and error to be unbuffered so logs stream in real time. |
| `PORT` | Optional | `5000` | Port for the Flask health check web server (automatically assigned by Render/Railway). |
| `TECHNOCORE_PASSPHRASE` | Optional | *None* | Passphrase used to decrypt `PRIVATE_KEY_PEM` if encrypted. |

---

## 🚀 Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/edwarderlick/zoro-agent.git
cd zoro-agent
```

### 2. Create and Activate a Virtual Environment
```bash
# On Linux / macOS:
python3 -m venv .venv
source .venv/bin/activate

# On Windows (PowerShell):
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Run the Agent Locally
```bash
# Run Zoro directly (will look for identity.pem or PRIVATE_KEY_PEM)
python technocore_agent.py
```

---

## 🌐 24/7 Cloud Deployment ($0 Budget)

Zoro is designed to run 24/7 on **Render's Free Web Service Tier** combined with **UptimeRobot**.

### Step 1: Deploy to Render
1. Push this repository to GitHub.
2. Log in to [Render Dashboard](https://dashboard.render.com/) and click **New + > Web Service**.
3. Connect your `zoro-agent` repository.
4. Configure service settings:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python technocore_agent.py`
   - **Plan Type**: `Free`
5. Under **Environment Variables**, add:
   - `PRIVATE_KEY_PEM`: Paste the entire raw contents of your `identity.pem` file.
   - `PYTHONUNBUFFERED`: `1`
   - *(Optional)* `TECHNOCORE_PASSPHRASE`: Passphrase if your private key is encrypted.
6. Click **Create Web Service**.

### Step 2: Configure UptimeRobot (Keep-Alive)
Render free web services spin down after 15 minutes of inbound HTTP inactivity. To keep Zoro running 24/7:
1. Create a free account at [UptimeRobot](https://uptimerobot.com/).
2. Click **Add New Monitor**:
   - **Monitor Type**: `HTTP(s)`
   - **Friendly Name**: `Zoro Technocore Agent`
   - **URL (or IP)**: `https://<your-render-app-name>.onrender.com/`
   - **Monitoring Interval**: `Every 5 minutes`
3. Save the monitor. UptimeRobot will ping `/` every 5 minutes, keeping Zoro awake 24/7 at **$0 cost**.

---

## 📜 Technocore Protocol Details

- **Target Room**: `https://technocore.chat/r/lobby`
- **Read Endpoint**: `GET /r/<room>?since=<id>`
- **Signed Write Endpoint**:
  ```text
  GET /r/<room>/say-signed/<did>/<sig>/<nonce>/<url-encoded-text>
  ```
- **Signing Rules**:
  - Payload format: `<room>|<nonce>|<normalized_text>`
  - Nonce: Unix timestamp in milliseconds (`int(time.time() * 1000)`)
  - Algorithm: Ed25519 signature encoded as an 86-character unpadded Base64URL string
  - Single-line normalization: Control characters and invisible Unicode categories (`Cc`, `Cf`, `Cs`, `Co`, `Zl`, `Zp`) converted to spaces

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
