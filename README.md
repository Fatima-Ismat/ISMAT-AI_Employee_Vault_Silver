# ISMAT AI Employee Vault - Silver Tier

The ISMAT AI Employee Vault is a personal AI assistant automating email, WhatsApp, and LinkedIn tasks. Tier: Silver (100% complete)

## Project Structure

silver/
├── backend/
│   ├── whatsapp_watcher.py
│   ├── linkedin_watcher.py
│   ├── gmail_watcher_oauth.py
│   └── server.py
├── config/
│   ├── .env
│   ├── .env.example
│   ├── whatsapp_session/
│   ├── linkedin_session/
│   └── rate_limits.json
├── vault/
│   ├── Inbox/
│   ├── Needs_Action/
│   ├── Pending_Approval/
│   ├── Approved/
│   ├── Briefings/
│   ├── Done/
│   └── Logs/
├── docs/
├── scripts/
├── skills/
├── specs/
├── tests/
├── .venv/
├── .gitignore
├── requirements.txt
├── pyproject.toml
├── README.md
└── uv.lock

## Key Features

- **WhatsApp Automation:** Watches messages, generates .md task files in `vault/Needs_Action/`.
- **LinkedIn Automation:** Reads notifications/messages; posts approved content from `vault/Pending_Approval/`.
- **Gmail Watcher:** App Password method; reads inbox and integrates with MCP server.
- **Vault Management:** Obsidian vault organizes tasks, approvals, and logs.
- **MCP Server:** Central backend server (`server.py`) for integrating all watchers and automation.

## Workflow Diagram

```mermaid
flowchart TD
    WA[WhatsApp Messages] -->|Scan + Watch| WW[whatsapp_watcher.py]
    WW --> VA[vault/Needs_Action/WA_*.md]

    LI[LinkedIn Notifications] -->|Scan + Watch| LW[linkedin_watcher.py]
    LW --> VA
    LW --> PA[vault/Pending_Approval/LI_*.md] -->|POST| LinkedIn



Installation & Setup
git clone https://github.com/Fatima-Ismat/ISMAT-AI_Employee_Vault_Silver.git
cd ISMAT-AI_Employee_Vault_Silver/silver/

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt

⚠️ Keep .env and config/whatsapp_session/, config/linkedin_session/ local. Do not push to GitHub.

Usage
# WhatsApp watcher
python backend/whatsapp_watcher.py

# LinkedIn watcher (READ mode)
python backend/linked_watcher.py --mode read

# LinkedIn watcher (POST mode)
python backend/linked_watcher.py --mode post
Notes

.gitignore prevents sensitive info and sessions from being pushed.

Empty folders (docs/, scripts/, specs/, tests/) kept for future tiers.

Demo instructions ready for video recording.
