# ISMAT AI Employee Vault - Silver Tier Overview

The ISMAT AI Employee Vault is a personal AI assistant automating email, WhatsApp, and LinkedIn tasks.

**Tier:** Silver (100% complete)  
**Project Location:** `D:\AI_Employee_Vault_Silver\silver\`

It integrates backend watchers, MCP server, and an organized Obsidian vault for task tracking.

---

## Project Structure

```text
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
Key Features

WhatsApp Automation: Watches messages, generates .md task files in vault/Needs_Action/. Session saved in config/whatsapp_session/.

LinkedIn Automation: Reads notifications/messages; posts approved content from vault/Pending_Approval/. Session saved in config/linkedin_session/.

Gmail Watcher: App Password method; reads inbox and integrates with MCP server.

Vault Management: Obsidian vault organizes tasks, approvals, and logs. Auto-generated .md files for tasks.

MCP Server: Central backend server (server.py) for integrating all watchers and automation.

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
python backend/linked_in_watcher.py --mode post
Workflow Diagram

Mermaid diagram will render on GitHub automatically.

GitHub Best Practices

.gitignore prevents sensitive info and sessions from being pushed.

Logs (vault/Logs/) and auto-generated files ignored.

Folders like docs/, scripts/, specs/, tests/ can be expanded in future tiers.

Keep local sessions only on your machine.
