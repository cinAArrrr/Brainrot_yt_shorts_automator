# 🧠 BrainRot Bot — Groq + Selenium Edition

Auto-generates and posts AI brainrot YouTube Shorts.

## Security note
Do **not** commit or share your API key or `persistent Chrome profile`. Treat both like passwords.

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

Run commands from the folder that contains the `brainrot_bot/` directory. A small launcher is also included at the ZIP root, so `python main.py ...` works there too.

Also install ffmpeg:
- **Linux:** `sudo apt install ffmpeg`
- **macOS:** `brew install ffmpeg`
- **Windows:** https://ffmpeg.org/download.html

### 2. Set your Groq API key
```bash
python main.py config --api-key YOUR_GROQ_KEY
```

You can also set `GROQ_API_KEY` in your environment.

### 3. Export your YouTube cookies
1. Install the **"Get persistent Chrome profile LOCALLY"** browser extension:
   - Chrome: https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc
   - Firefox: https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/
2. Go to **https://www.youtube.com** and make sure you're logged in
3. Click the extension icon → select **youtube.com** → **Export**
4. Save the file as **`persistent Chrome profile`** in this folder

## Usage

| Command | What it does |
|---|---|
| `python main.py start` | Post hourly, forever |
| `python brainrot_bot/main.py start` | Same command from the subfolder |
| `python main.py start --interval 30` | Post every 30 minutes |
| `python main.py start --topic "space facts"` | Lock to one topic |
| `python main.py generate` | Preview a video (no upload) |
| `python main.py generate --topic "dark history" --output out.mp4` | Generate to file |
| `python main.py upload video.mp4 --title "My Short #Shorts"` | Upload a specific file |
| `python main.py check` | Verify persistent Chrome profile |
| `python main.py config` | View config |
| `python main.py encrypt` | Encrypt `config.json` and `cookies.txt` with a passphrase |
| `python main.py decrypt` | Decrypt the `.enc` files back to plaintext |

## File structure

```
brainrot_bot/
├── main.py
├── cookie_auth.py
├── cookie_uploader.py
├── generator.py
├── scheduler.py
├── config.py
├── requirements.txt
├── persistent Chrome profile
├── config.json
└── brainrot_bot.log
```

## Troubleshooting

**"persistent Chrome profile not found"** → Export from your browser as described above. If Google sends you back to the login page, re-export cookies from the same browser profile while logged in.

**Upload fails / 401 error** → Cookies expired — re-export from browser while logged in to YouTube.

**Video renders slowly** → Normal on CPU (1–3 min per video). Rendering happens before upload.

**"API key not set"** → Run `python main.py config --api-key YOUR_KEY`.

## Encrypting your secrets at rest

`config.json` (Groq API key) and `cookies.txt` (YouTube session) are personal
secrets. To keep them out of the clear when this folder is zipped or copied:

```bash
python main.py encrypt   # asks for a passphrase, writes config.json.enc and
                         # cookies.txt.enc, deletes the plaintext originals
python main.py decrypt   # reverse
```

The encryption uses Fernet (AES-128-CBC + HMAC-SHA256) with a key derived
from your passphrase via PBKDF2-HMAC-SHA256, 200,000 iterations, with a fresh
random salt per file.

While encrypted, the bot prompts for the passphrase the first time it needs
to read a secret. For unattended runs (e.g. `start` under a scheduler) set
`BRAINROT_PASSPHRASE` in the environment and the bot won't prompt:

```bash
export BRAINROT_PASSPHRASE='your passphrase'
python main.py start
```

**Lose the passphrase, lose the data** -- there is no recovery.


## Visual theme

The render pipeline now uses an original cinematic dark theme, an on-video watermark, and a generated ambient background bed under the voiceover.
