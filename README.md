# Privacy Summarizer

**Privacy-focused Signal group chat summaries with time-limited data retention.**

Privacy Summarizer generates summaries of Signal group chats using a self-hosted language model, with automatic message purging. Messages are stored temporarily in an encrypted database (default 48 hours), summarized, then automatically deleted.

## 🔒 Privacy Guarantees

**What gets stored (encrypted at rest with SQLCipher):**
- Messages (temporary, purged after 48 hours by default, configurable per schedule)
- Reactions (for engagement metrics, purged with messages)
- Group names and IDs
- Schedule configurations
- Summary run metadata (execution time, message count, status - NOT the summary text itself)

**What NEVER gets stored:**
- ❌ User names or profiles
- ❌ Phone numbers
- ❌ Attachments
- ❌ Any data beyond retention period

**Privacy features:**
- All data encrypted at rest with SQLCipher
- Summary prompts explicitly forbid names and direct quotes
- Summaries use generic terms ("participants", "the group", "someone")
- Participant count estimated, not tracked
- Automatic purge of expired messages (runs hourly)
- Configurable retention periods per schedule

## Features

- **Scheduled Summaries**: Automatically post privacy-focused summaries to Signal groups
- **On-Demand Summaries**: Generate summaries for specific groups on-the-fly
- **DM Chat**: Direct message the bot for conversational AI chat or text summarization
- **Time-Limited Storage**: Messages stored temporarily, auto-purged after retention period
- **Privacy-First**: Summaries never include names or direct quotes
- **Encrypted Storage**: All data encrypted with SQLCipher
- **Flexible Scheduling**: Daily or weekly summaries with timezone support
- **Self-Hosted**: Uses Ollama for on-premise inference (no cloud)
- **Web UI**: Optional React frontend for schedule management
- **In-Chat Commands**: `!help`, `!status`, `!summary`, `!opt-out`, `!!!purge` commands in Signal and DMs

## Architecture

- **Python 3.11**: Core application
- **signal-cli**: Signal messenger integration
- **SQLCipher**: Encrypted SQLite database
- **Ollama**: Self-hosted language model (no cloud, no data leakage)
- **Docker**: Containerized deployment
- **APScheduler**: Automated scheduling for summaries
- **FastAPI**: REST API for web UI (optional)
- **React**: Web frontend for schedule management (optional)

## Prerequisites

Before you begin, ensure you have:

1. **Docker & Docker Compose** installed
2. **Ollama** installed and running on the host machine
   - Install from: https://ollama.ai
   - Pull the model: `ollama pull mistral-nemo`
3. **A Signal account** with a phone number you can use
4. **Membership in Signal group chats** you want to summarize

## ⚠️ Important: Linking vs Registration

**If you already use Signal on your phone, you want to LINK, not REGISTER!**

### Two Setup Options:

| Option | When to Use | Command | Result |
|--------|-------------|---------|--------|
| **Linking** (Recommended) | You already use Signal on iPhone/Android | `docker-compose run --rm privacy-summarizer python -m src.main link` | Adds signal-cli as a secondary device alongside your phone |
| **Registration** | Brand new number, no existing Signal | `docker-compose run --rm privacy-summarizer python -m src.main setup` | Makes signal-cli your primary device (kicks out other devices!) |

**⚠️ CAUTION:** Registration will **kick out your existing Signal app**. Always use linking if you have Signal on your phone!

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/yourusername/privacy-summarizer.git
cd privacy-summarizer

# Copy environment file
cp .env.example .env

# Edit .env and set:
# - SIGNAL_PHONE_NUMBER=+1234567890
# - ENCRYPTION_KEY (generate with: python -c "import secrets; print(secrets.token_urlsafe(32))")
nano .env
```

### 2. Build Docker Image

```bash
docker-compose build
```

### 3. Link Signal Account (Recommended)

```bash
# Generate linking QR code
docker-compose run --rm privacy-summarizer python -m src.main link

# Follow on-screen instructions:
# 1. Convert the sgnl:// URI to a QR code
# 2. Scan with your Signal app (Settings → Linked Devices)
# 3. Verify it worked:
docker-compose run --rm privacy-summarizer python -m src.main status
```

See [LINKING.md](LINKING.md) for detailed linking instructions.

### 4. Create a Schedule

```bash
# Create a daily summary schedule
docker-compose run --rm privacy-summarizer python -m src.main schedule-summary add \
  --name "Daily General Chat Summary" \
  --source-group "General Chat" \
  --target-group "Summary Channel" \
  --type daily \
  --times 08:00 --times 20:00 \
  --timezone "America/Chicago" \
  --period-hours 24

# Verify schedule was created
docker-compose run --rm privacy-summarizer python -m src.main schedule-summary list
```

### 5. Start Daemon

```bash
# Start in daemon mode (runs scheduled summaries)
docker-compose up -d

# Check logs
docker-compose logs -f
```

## Usage

### Scheduled Summaries (Daemon Mode)

**Daily Summaries:**
```bash
# Add daily schedule
docker-compose run --rm privacy-summarizer python -m src.main schedule-summary add \
  --name "Morning Digest" \
  --source-group "Team Chat" \
  --target-group "Team Summaries" \
  --type daily \
  --times 09:00 \
  --timezone "US/Eastern" \
  --period-hours 24
```

**Weekly Summaries:**
```bash
# Add weekly schedule
docker-compose run --rm privacy-summarizer python -m src.main schedule-summary add \
  --name "Weekly Roundup" \
  --source-group "Team Chat" \
  --target-group "Team Summaries" \
  --type weekly \
  --day-of-week sunday \
  --time 20:00 \
  --timezone "US/Eastern"
```

**Manage Schedules:**
```bash
# List all schedules
docker-compose run --rm privacy-summarizer python -m src.main schedule-summary list

# Test a schedule (dry-run, no posting)
docker-compose run --rm privacy-summarizer python -m src.main schedule-summary run-now \
  --name "Morning Digest" \
  --dry-run

# Disable/enable schedules
docker-compose run --rm privacy-summarizer python -m src.main schedule-summary disable --name "Morning Digest"
docker-compose run --rm privacy-summarizer python -m src.main schedule-summary enable --name "Morning Digest"

# Remove schedule
docker-compose run --rm privacy-summarizer python -m src.main schedule-summary remove --name "Morning Digest"
```

### On-Demand Summaries

```bash
# Generate summary for a specific group
docker-compose run --rm privacy-summarizer python -m src.main summarize \
  --group "General Chat" \
  --hours 24

# Summary is printed to console (not posted to Signal)
```

### Accept Group Invites

```bash
# List pending group invites
docker-compose run --rm privacy-summarizer python -m src.main accept-invite --list

# Accept all pending invites
docker-compose run --rm privacy-summarizer python -m src.main accept-invite

# Accept a specific group invite
docker-compose run --rm privacy-summarizer python -m src.main accept-invite --group-id "GROUP_ID"
```

### In-Chat Bot Commands (Groups)

When the daemon is running, you can use these commands in any group:

| Command | Description | Permission |
|---------|-------------|------------|
| `!help` | Show available commands | Everyone |
| `!status` | Show bot status and current retention | Everyone |
| `!summary [hours]` | Generate summary (default: retention period) | Everyone |
| `!opt-out` | Stop collecting your messages (deletes existing) | Everyone |
| `!opt-in` | Resume message collection | Everyone |
| `!retention` | View current message retention period | Everyone |
| `!retention [hours]` | Set fixed retention period (1-168 hours) | 🔒 Admins |
| `!retention signal` | Follow Signal's disappearing messages setting | 🔒 Admins |
| `!power` | View who can run config commands | Everyone |
| `!power [admins\|everyone]` | Set permission level | 🔒 Admins |
| `!!!purge` | Purge all stored messages for this group | 🔒 Admins |

**Permissions:** By default, only room admins can run configuration commands (🔒). Admins can run `!power everyone` to allow all members to configure. `!power` itself is always admin-only.

**Opt-Out:** Users can opt out of message collection per-group using `!opt-out`. When opting out, existing stored messages are immediately deleted. No admin permission needed - users control their own data. Use `!opt-in` to resume.

**Auto-Retention from Signal:** When Signal's disappearing messages are enabled, Privacy Summarizer automatically matches that retention period. Use `!retention [hours]` to override with a fixed value, or `!retention signal` to re-enable auto-sync.

### Direct Message (DM) Chat

Send a direct message to the bot's Signal number for conversational AI chat:

**Features:**
- **Conversational AI**: Chat back-and-forth like ChatGPT
- **Text Summarization**: Paste long text or say "summarize this" to get a summary
- **Conversation History**: Full context maintained (auto-purged based on your retention setting)
- **Custom Retention**: Set your own retention period (1-168 hours) via `!retention` command
- **Kill Switch**: Can be disabled while keeping the bot running

**DM Commands:**

| Command | Description |
|---------|-------------|
| `!help` | Show available DM commands |
| `!status` | Show bot and AI status, message count |
| `!summary` | Summarize conversation history and clear it |
| `!retention` | View your message retention period |
| `!retention [hours]` | Set retention period (1-168 hours, default 48) |
| `!!!purge` | Delete all conversation history immediately |

**Examples:**
```
You: What's the capital of France?
Bot: The capital of France is Paris...

You: [paste long article]
Bot: Summary: The article discusses...

You: !summary
Bot: 📋 Conversation Summary: [summary of your chat] ✓ 8 messages cleared.
```

**CLI Management:**
```bash
# Check DM feature status
docker-compose run --rm privacy-summarizer python -m src.main dm status

# Disable DM chat (kill switch)
docker-compose run --rm privacy-summarizer python -m src.main dm disable

# Enable DM chat
docker-compose run --rm privacy-summarizer python -m src.main dm enable

# Purge all DM messages
docker-compose run --rm privacy-summarizer python -m src.main dm purge --all
```

### Signal Status & Troubleshooting

```bash
# Check Signal registration status
docker-compose run --rm privacy-summarizer python -m src.main status

# View daemon logs
docker-compose logs -f

# Restart daemon (to pick up schedule changes)
docker-compose restart
```

## How Privacy Summarizer Works

### Data Flow

1. **Real-Time Message Collection** (continuous):
   - Daemon polls signal-cli every few seconds for new messages
   - Messages stored immediately in encrypted SQLCipher database
   - Deduplicated by `(timestamp, sender_uuid, group_id)`
   - Reactions stored for engagement metrics

2. **Summary Generation** (at scheduled times):
   - Messages queried from database for the configured time window
   - Content sent to local Ollama model
   - Model explicitly instructed: NO names, NO direct quotes
   - Summary posted to target Signal group
   - Summary discarded after posting (not stored)

3. **Automatic Purge** (hourly):
   - Messages older than retention period deleted (default 48 hours)
   - Each schedule can have its own retention period

### Summary Format

Summaries include:
- **Message count** (number only, no content)
- **Estimated participant count** (not tracked individually)
- **Sentiment** (positive/negative/neutral/mixed)
- **Topics discussed** (generic themes, no names)
- **Summary text** (no quotes, generic terms like "participants", "the group")
- **Action items** (anonymized, passive voice)

**Example Summary:**
```
📊 Summary: General Chat
⏰ Last 24 hours

💬 Messages: 47
👥 Participants: 8
💭 Sentiment: 😊 Positive

📋 Topics Discussed:
  • Weekend plans
  • Project deadline updates
  • Team lunch scheduling

📝 Summary:
The group discussed upcoming weekend activities and coordinated on
project timelines. Participants agreed to finalize deliverables by
Friday. General consensus was positive about team lunch plans.

✅ Action Items:
  • Finalize project deliverables by Friday
  • Confirm team lunch attendance

---
🔒 Privacy Summarizer
```

## Configuration

### Environment Variables (.env)

**Required:**
```bash
SIGNAL_PHONE_NUMBER=+1234567890
ENCRYPTION_KEY=your-secure-key-here  # Generate with secrets.token_urlsafe(32)
```

**Optional:**
```bash
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=mistral-nemo
DB_PATH=/data/privacy_summarizer.db
TIMEZONE=UTC
LOG_LEVEL=INFO

# Message Collection Reliability (recommended defaults shown)
MESSAGE_COLLECTION_ATTEMPTS=3  # Number of receive attempts for completeness
MESSAGE_COLLECTION_TIMEOUT=30   # Timeout per attempt in seconds
```

**Why multiple attempts?** Signal-CLI may not return all queued messages in a single call due to batching limits. Multiple attempts with deduplication ensure complete message collection, which is critical for transient processing where there's no second chance to retrieve missed messages.

### Generating Encryption Key

```bash
# Generate a secure encryption key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Add the generated key to your `.env` file as `ENCRYPTION_KEY`.

## Platform-Specific Notes

### macOS/Linux (Default)

```bash
# Daemon only
docker-compose up -d

# Full stack (daemon + API + web UI)
docker-compose -f docker-compose.full.yml up -d
```

### Windows

```bash
# Daemon only
docker-compose -f docker-compose.windows.yml up -d

# Full stack (daemon + API + web UI)
docker-compose -f docker-compose.full.yml up -d
```

### NAS (Synology, QNAP, TrueNAS)

```bash
# Use NAS-specific compose file
docker-compose -f docker-compose.nas.yml up -d
```

### Full Stack with Web UI

The full stack includes:
- **Daemon**: Message collection and scheduled summaries
- **API**: REST API on port 8000 (configurable via `API_PORT`)
- **Frontend**: React web UI on port 3000 (configurable via `FRONTEND_PORT`)

```bash
# Start full stack
docker-compose -f docker-compose.full.yml up -d

# Access web UI at http://localhost:3000
# API docs at http://localhost:8000/api/docs
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for platform-specific instructions.

## Troubleshooting

### "Not registered" error
```bash
# Link your Signal account
docker-compose run --rm privacy-summarizer python -m src.main link
```

### "No groups found"
Ensure your Signal account is a member of group chats. Check with your Signal app on your phone.

### Ollama connection fails
```bash
# Verify Ollama is running
ollama list

# Test connectivity from container
docker-compose run --rm privacy-summarizer curl http://host.docker.internal:11434/api/tags
```

### Encryption errors
Ensure `ENCRYPTION_KEY` is set in your `.env` file. If pysqlcipher3 fails to install, encryption will fall back to unencrypted SQLite (not recommended for production).

### Schedule not running
```bash
# Restart daemon to pick up schedule changes
docker-compose restart

# Check logs for errors
docker-compose logs -f
```

## Data Retention Policy

**Privacy Summarizer uses time-limited data retention.**

| Data Type | Retention Period | Configurable |
|-----------|------------------|--------------|
| Group messages | 48 hours (default) | Yes, via `!retention` command or per schedule |
| DM messages | 48 hours (default) | Yes, via `!retention` command or `DM_RETENTION_HOURS` |
| Reactions | Same as messages | Yes |
| Summary text | Not stored | N/A |
| Group metadata | Permanent | No |
| Schedules | Permanent | No |

**Retention Priority (groups):**
1. Per-group settings via `!retention` command
2. Auto-sync from Signal's disappearing messages setting
3. Per-schedule `retention_hours` configuration
4. Global default (`DEFAULT_MESSAGE_RETENTION_HOURS`, 48 hours)

**Purge runs hourly** to delete expired data. Messages can also be purged immediately with `!!!purge` command.

## Security Considerations

1. **Database Encryption**: All data encrypted with SQLCipher (AES-256)
2. **Self-Hosted Model**: Ollama runs on-premise, no cloud services
3. **Time-Limited Storage**: Messages auto-purged after retention period
4. **Privacy-First Prompts**: Model explicitly instructed to omit names and quotes
5. **No Identifiers**: Only UUIDs stored (for deduplication), no names or phone numbers
6. **Encrypted Signal**: Uses Signal's end-to-end encryption via signal-cli

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- **signal-cli**: Signal messenger command-line interface
- **Ollama**: Self-hosted language model inference
- **SQLCipher**: Encrypted SQLite database

## Contributing

Contributions welcome! Please open issues or pull requests on GitHub.

## Support

For issues or questions:
- GitHub Issues: https://github.com/yourusername/privacy-summarizer/issues
- Documentation: See CLAUDE.md for technical details
