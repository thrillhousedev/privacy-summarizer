# Deployment Guide

This guide covers deploying Signal Summarizer on different platforms.

## Prerequisites

All platforms need:
- Docker and Docker Compose installed
- Tailscale (for accessing thrilltop.mesh.thrill.host)
- Ollama running somewhere (local or remote)

## Platform-Specific Instructions

### 🪟 Windows Desktop

**Requirements:**
- Windows 10/11 with WSL2
- Docker Desktop for Windows
- Tailscale for Windows

**Setup:**

1. **Clone the repository:**
   ```powershell
   cd C:\Users\YourName
   git clone <repo-url> privacy-summarizer
   cd privacy-summarizer
   ```

2. **Configure environment:**
   ```powershell
   copy .env.example .env
   notepad .env
   ```

   Update:
   ```env
   SIGNAL_PHONE_NUMBER=+1234567890
   OLLAMA_HOST=http://thrilltop.mesh.thrill.host:11434
   ```

3. **Use Windows-specific compose file:**
   ```powershell
   docker-compose -f docker-compose.windows.yml build
   docker-compose -f docker-compose.windows.yml run --rm privacy-summarizer python -m src.main setup
   ```

4. **Start the daemon:**
   ```powershell
   docker-compose -f docker-compose.windows.yml up -d
   ```

**Tips:**
- Data stored in `.\data`, `.\exports`, `.\signal-cli-config`
- View logs: `docker-compose -f docker-compose.windows.yml logs -f`
- Stop: `docker-compose -f docker-compose.windows.yml down`

---

### 🗄️ NAS (Synology/QNAP/TrueNAS)

**Best for:** Always-on deployment, centralized data storage

#### Synology NAS

**Requirements:**
- DSM 7.0 or higher
- Container Manager (formerly Docker) package installed
- Tailscale package installed

**Setup via SSH:**

1. **SSH into your NAS:**
   ```bash
   ssh admin@your-nas.local
   ```

2. **Create project directory:**
   ```bash
   cd /volume1/docker  # or your preferred location
   git clone <repo-url> privacy-summarizer
   cd privacy-summarizer
   ```

3. **Configure:**
   ```bash
   cp .env.example .env
   nano .env
   ```

   Update:
   ```env
   SIGNAL_PHONE_NUMBER=+1234567890
   OLLAMA_HOST=http://thrilltop.mesh.thrill.host:11434
   ```

4. **Build and setup:**
   ```bash
   docker-compose -f docker-compose.nas.yml build
   docker-compose -f docker-compose.nas.yml run --rm privacy-summarizer python -m src.main setup
   ```

5. **Start daemon:**
   ```bash
   docker-compose -f docker-compose.nas.yml up -d
   ```

**Synology Container Manager UI:**

Alternatively, import the project via Container Manager:
1. Upload project folder to `/docker/privacy-summarizer`
2. Container Manager → Project → Create
3. Set Project Path and compose file
4. Configure environment variables
5. Start the project

#### QNAP/TrueNAS

Similar process - use Container Station (QNAP) or Apps (TrueNAS) with the `docker-compose.nas.yml` file.

---

### 🍎 macOS (Current Setup)

**Already configured!** You're currently using:
```bash
docker-compose build
docker-compose run --rm privacy-summarizer python -m src.main setup
docker-compose up -d
```

The main `docker-compose.yml` uses `network_mode: host` which works on macOS via Docker Desktop.

---

## Transferring Setup Between Machines

### Option 1: Transfer Registered Account

After registering on one machine, you can transfer to another:

1. **On source machine:**
   ```bash
   # Tar up the signal-cli config (contains your registration)
   tar -czf signal-cli-backup.tar.gz signal-cli-config/
   ```

2. **On destination machine:**
   ```bash
   # Extract the config
   tar -xzf signal-cli-backup.tar.gz

   # Update .env with same phone number
   # Build and start
   docker-compose -f docker-compose.<platform>.yml up -d
   ```

### Option 2: Fresh Registration

Register separately on each machine (requires re-registration with Signal).

---

## Running Ollama Locally on Each Platform

### Windows
```powershell
# Install Ollama
winget install Ollama.Ollama

# Pull model
ollama pull mistral-nemo

# Update .env
OLLAMA_HOST=http://localhost:11434
```

### NAS (if supported)
Some NAS systems can run Ollama in a container:
```bash
docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
docker exec -it ollama ollama pull mistral-nemo
```

Update `.env`:
```env
OLLAMA_HOST=http://localhost:11434
```

Then use `network_mode: host` in `docker-compose.nas.yml`.

---

## Recommended Deployment

Based on your setup:

1. **Primary: NAS** (always-on, centralized)
   - Best for reliability
   - Access reports from any device
   - Lower power consumption than desktop

2. **Secondary: Windows Desktop** (for testing/development)
   - Easy access
   - Full desktop environment

Keep Ollama on `thrilltop` - it's powerful and already set up!

---

## Viewing Summaries

Privacy Summarizer posts summaries directly to Signal groups. There are no markdown exports.

To view summaries:
- Check your Signal app on your phone/desktop
- Summaries appear in the configured target groups
- Use `--dry-run` flag to preview summaries without posting:
  ```bash
  docker-compose run --rm privacy-summarizer python -m src.main schedule-summary run-now --name "Schedule Name" --dry-run
  ```

---

## Troubleshooting

### Signal-CLI issues
All platforms use linux/amd64 emulation for signal-cli compatibility.

### Tailscale connectivity
Ensure Tailscale is running on the host machine (not in Docker).

### Ollama connectivity
Test from host:
```bash
curl http://thrilltop.mesh.thrill.host:11434/api/tags
```

If that works but Docker can't reach it, check Docker network settings.

### Permissions
NAS may need:
```bash
sudo chown -R 1000:1000 data exports signal-cli-config
```

---

## Monitoring

### View logs
```bash
# Windows
docker-compose -f docker-compose.windows.yml logs -f

# NAS
docker-compose -f docker-compose.nas.yml logs -f

# macOS
docker-compose logs -f
```

### Check status
```bash
docker-compose -f docker-compose.<platform>.yml run --rm privacy-summarizer python -m src.main status
```

### Manual export
```bash
docker-compose -f docker-compose.<platform>.yml run --rm privacy-summarizer python -m src.main summarize
```

---

## Backup Strategy

Important files to backup:
1. `signal-cli-config/` - Your Signal registration (required to link device)
2. `data/privacy_summarizer.db` - Encrypted schedule configurations and group metadata only (no message history)
3. `.env` - Your configuration including ENCRYPTION_KEY

**Note:** Privacy Summarizer does NOT store message history. Only minimal encrypted metadata is stored (group names, schedules, last run timestamps).

Recommended:
- Backup to cloud storage (data is already encrypted)
- Keep encrypted backup of signal-cli-config
- Store ENCRYPTION_KEY securely (required to access database)
