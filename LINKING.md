# Linking Signal Summarizer as a Secondary Device

This guide explains how to link signal-cli as a **secondary device** to your existing Signal account, rather than registering it as a primary device.

## Registration vs Linking: What's the Difference?

### Registration (Primary Device)
- Creates a **new Signal account** with your phone number
- **Replaces** any existing Signal registration on that number
- **Kicks out** your iPhone/Android app and Signal Desktop
- You can only have **ONE primary device** per phone number

### Linking (Secondary Device)
- Adds signal-cli as a **linked device** to your existing account
- **Keeps** your iPhone/Android as the primary device
- Works **alongside** Signal Desktop and other linked devices
- You can have up to **5 linked devices**

**TL;DR:** If you already use Signal on your phone, you want **LINKING**, not registration!

---

## When You Accidentally Registered Instead

If you ran `setup` and it kicked out your iPhone/Android:

### What Happened
1. signal-cli became your **PRIMARY** device
2. Your iPhone was logged out
3. You had to log back in on iPhone (making it primary again)
4. Now signal-cli has an **orphaned** primary registration

### Fix It

**Step 1: Clear the orphaned registration**
```bash
rm -rf signal-cli-config/data/*
```

**Step 2: Follow the linking process below**

---

## How to Link Signal Summarizer

### Prerequisites
- ✅ Signal already installed and working on your iPhone/Android
- ✅ Your phone number registered with Signal
- ✅ Signal Summarizer Docker image built

### Step 1: Clear Any Existing Registration

If you previously ran `setup`, clear it first:

```bash
# Remove old registration data
rm -rf signal-cli-config/data/*

# Verify it's clean
ls -la signal-cli-config/data/  # Should be empty or not exist
```

### Step 2: Run the Link Command

```bash
docker-compose run --rm privacy-summarizer python -m src.main link
```

You'll see:
```
======================================================================
Signal Device Linking
======================================================================

Phone Number: +1234567890
Device Name: signal-exporter

⚠️  IMPORTANT: This will link signal-cli as a SECONDARY device.
   Your phone will remain your PRIMARY device.
   Make sure you've removed any old registrations first!

Continue? (yes/no):
```

Type `yes` and press Enter.

### Step 3: Generate QR Code

The command will output a linking URI like:
```
sgnl://linkdevice?uuid=xxxxx&pub_key=yyyyy
```

**Copy this entire URI** and convert it to a QR code:

#### Option A: Online QR Generator (Easiest)

1. Go to https://www.qr-code-generator.com/
2. Select **"URL"** type
3. Paste the `sgnl://linkdevice?...` URI
4. Click **"Create QR Code"**
5. Download or screenshot the QR code

#### Option B: Command Line (Mac/Linux)

Install qrencode:
```bash
# macOS
brew install qrencode

# Linux
sudo apt-get install qrencode
```

Generate QR in terminal:
```bash
qrencode -t ansiutf8 'sgnl://linkdevice?uuid=xxxxx&pub_key=yyyyy'
```

Or save as PNG:
```bash
qrencode -o qr-code.png 'sgnl://linkdevice?uuid=xxxxx&pub_key=yyyyy'
```

### Step 4: Scan with Your Phone

On your iPhone/Android:

1. Open **Signal**
2. Tap **Settings** (or your profile picture)
3. Tap **Linked Devices**
4. Tap the **+** (plus) button
5. **Scan the QR code** you generated

You'll see "signal-exporter" appear in your linked devices list!

### Step 5: Verify

Check that linking was successful:

```bash
docker-compose run --rm privacy-summarizer python -m src.main status
```

You should see:
```
✓ Registered: Yes
✓ Groups: X
```

---

## Troubleshooting

### "Linking URI expired"

The URI is only valid for **~90 seconds**. If it expires:
1. Run the `link` command again to generate a new URI
2. Generate the QR code faster this time
3. Have your phone ready before running the command

### "Invalid QR code" when scanning

Make sure you:
- Copied the **entire** `sgnl://linkdevice?...` URI (not just part of it)
- Didn't add any extra spaces or characters
- Used the QR generator correctly

### Phone not showing linked device

After scanning, check:
- Signal → Settings → Linked Devices
- You should see "signal-exporter" listed

If not:
- Try linking again
- Make sure your phone has internet connection
- Restart Signal app on your phone

### signal-cli still shows "not registered"

After linking, signal-cli needs to sync:

```bash
docker-compose run --rm privacy-summarizer python -m src.main collect --timeout 60
```

This will sync your contacts and groups. Then check status again.

### I still see the old primary registration

Clear it completely:
```bash
# Stop any running containers
docker-compose down

# Remove ALL signal-cli data
rm -rf signal-cli-config/*

# Start fresh with linking
docker-compose run --rm privacy-summarizer python -m src.main link
```

---

## Using Linked Device

Once linked, Privacy Summarizer can:
- ✅ Receive messages from all your groups (transiently, no storage)
- ✅ Send summaries to groups
- ✅ Run the daemon for scheduled summaries
- ✅ Generate privacy-focused AI summaries (no names, no quotes)

What Privacy Summarizer does **NOT** do:
- ❌ Download attachments (privacy-focused, not needed)
- ❌ Store messages or user data (zero data retention)
- ❌ Track individual participants
- ❌ Generate exports or reports (summaries posted to Signal only)

What linked devices **cannot** do:
- ❌ Register new devices (only primary can do this)
- ❌ Unlink other devices (only primary can do this)
- ❌ Receive SMS verification codes

This is perfect for privacy-focused group summaries!

---

## Managing Linked Devices

### View Linked Devices

On your iPhone/Android:
- Signal → Settings → Linked Devices

You'll see all linked devices including:
- Signal Desktop
- signal-exporter
- Other linked phones/tablets

### Unlink signal-exporter

If you want to remove signal-cli:

**On your phone:**
1. Signal → Settings → Linked Devices
2. Tap "signal-exporter"
3. Tap "Unlink Device"

**On your computer:**
```bash
# Clean up the local data
docker-compose down
rm -rf signal-cli-config/*
```

---

## Best Practices

1. **Always link, never register** if you use Signal on your phone
2. **Clear old data** before linking to avoid confusion
3. **Name your device** descriptively (use `--name` flag)
4. **Keep your phone** as the primary device
5. **Backup** `signal-cli-config/` directory (contains your linked device keys)

---

## Transferring Linked Device

If you want to move signal-exporter to another machine:

1. **On source machine:**
   ```bash
   tar -czf signal-linked-device.tar.gz signal-cli-config/
   ```

2. **On destination machine:**
   ```bash
   tar -xzf signal-linked-device.tar.gz
   docker-compose run --rm privacy-summarizer python -m src.main status
   ```

The linked device registration transfers with the config directory!

---

## Summary

| Action | Command | Result |
|--------|---------|--------|
| **Link as secondary** | `docker-compose run --rm privacy-summarizer python -m src.main link` | ✅ Keeps your phone as primary |
| **Register as primary** | `docker-compose run --rm privacy-summarizer python -m src.main setup` | ⚠️ Kicks out your phone |
| **Check status** | `docker-compose run --rm privacy-summarizer python -m src.main status` | Shows registration type |
| **Clear registration** | `rm -rf signal-cli-config/data/*` | Removes all Signal data |

**Remember:** If you already use Signal on your phone, always use `link`, not `setup`!
