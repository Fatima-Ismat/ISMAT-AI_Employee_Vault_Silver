ISMAT AI Employee Vault - Silver Tier
Overview

The ISMAT AI Employee Vault is a personal AI assistant automating email, WhatsApp, and LinkedIn tasks.
Tier: Silver (100% complete)
Project Location: D:\AI_Employee_Vault_Silver\silver\

It integrates backend watchers, MCP server, and an organized Obsidian vault for task tracking.

Project Structure
silver/
├── backend/
│   ├── whatsapp_watcher.py      # WhatsApp automation (QR session in config/)
│   ├── linkedin_watcher.py      # LinkedIn READ + POST automation
│   ├── gmail_watcher_oauth.py   # Gmail automation backup (OAuth-ready)
│   └── server.py                # MCP server
├── config/
│   ├── .env                     # App passwords
│   ├── .env.example             # Template
│   ├── whatsapp_session/        # Local session (excluded from repo)
│   ├── linkedin_session/        # Local session (excluded from repo)
│   └── rate_limits.json         # API rate limits
├── vault/                        # Obsidian vault
│   ├── Inbox/
│   ├── Needs_Action/
│   ├── Done/
│   ├── Plans/
│   ├── Pending_Approval/
│   ├── Approved/
│   ├── Briefings/
│   └── Logs/
├── docs/                         # Documentation
├── history/                      # Logs & history
├── scripts/                       # Helper scripts
├── skills/                        # Skills modules (Gmail, LinkedIn, WhatsApp)
├── specs/                         # Specifications / requirements
├── tests/                         # Test files
├── .venv/                         # Python environment
├── .gitignore
├── requirements.txt
├── pyproject.toml
├── README.md
└── uv.lock
Key Features

WhatsApp Automation
Watches messages, generates .md task files in vault/Needs_Action/.
Session saved in config/whatsapp_session/.

LinkedIn Automation
Reads notifications/messages; posts approved content from vault/Pending_Approval/.
Session saved in config/linkedin_session/.

Gmail Watcher
App Password method; reads inbox and integrates with MCP server.

Vault Management
Obsidian vault organizes tasks, approvals, and logs. Auto-generated .md files for tasks.

MCP Server
Central backend server (server.py) for integrating all watchers and automation.

Installation & Setup

git clone https://github.com/Fatima-Ismat/ISMAT-AI_Employee_Vault_Silver.git
cd ISMAT-AI_Employee_Vault_Silver/silver/

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

⚠️ Keep .env and config/whatsapp_session/, config/linkedin_session/ local. Do not push to GitHub.

Usage
# Run WhatsApp watcher
python backend/whatsapp_watcher.py

# Run LinkedIn watcher (READ mode)
python backend/linkedin_watcher.py --mode read

# Run LinkedIn watcher (POST mode)
python backend/linkedin_watcher.py --mode post


Workflow Diagram (Mermaid)


---

## Workflow Diagram

```mermaid
flowchart TD
    subgraph WhatsApp
        WA[WhatsApp Messages] -->|Scan + Watch| WW[whatsapp_watcher.py]
        WW --> VA[vault/Needs_Action/WA_*.md]
    end

    subgraph LinkedIn
        LI[LinkedIn Notifications] -->|Scan + Watch| LW[linkedin_watcher.py]
        LW --> VA
        LW --> PA[vault/Pending_Approval/LI_*.md] -->|POST| LinkedIn
    end

    subgraph Vault
        VA --> Done[vault/Done]
        PA --> Approved[vault/Approved]
        VA --> Logs[vault/Logs]
    end

    subgraph MCP
        MCP[Server / MCP Tools] --> WW
        MCP --> LW
        MCP --> Gmail[gmail_watcher_oauth.py]
        Gmail --> VA
    end

Mermaid diagram will render on GitHub automatically.

GitHub Best Practices

.gitignore prevents sensitive info and sessions from being pushed.

Logs (vault/Logs/) and auto-generated files ignored.

Folders like docs/, scripts/, specs/, tests/ can be expanded in future tiers.

Keep local sessions only on your machine.

Demo & Submission

Show project structure.

Run WhatsApp watcher: python backend/whatsapp_watcher.py

Run LinkedIn watcher (read + post).

Show vault/Needs_Action/ files.

Record video → uploaded YouTube  video link → 
