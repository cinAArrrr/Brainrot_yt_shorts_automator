# 🏛️ Court Chronicles Bot

> **Fully automated AI courtroom YouTube Shorts — generates, voices, and uploads every hour. Free forever.**

A Python bot that writes dramatic courtroom scripts using AI, renders them as stylish vertical videos with animated character avatars and multiple voices, and uploads them directly to YouTube Shorts — all without any Google Cloud account or paid API.

---

## 📺 What it makes

Each video is a self-contained courtroom drama Short with:

- **AI-generated script** — Groq (free) writes a multi-character courtroom dialogue about a random wild scenario
- **Multiple voices** — each character (Judge, Lawyer, Karen, Defense Attorney) speaks in a distinct Microsoft Edge TTS voice, completely free
- **AI courtroom background** — Pollinations.ai generates a fresh photorealistic courtroom scene for every video, no API key needed
- **Animated character avatars** — four bouncing cartoon characters light up and lip-sync when they speak
- **Word-by-word captions** — Impact font, yellow with black outline, synced to each speaker
- **Pinned hook title** — bold two-line title card stays at the top throughout ("KAREN DESTROYS $300K FERRARI")
- **Courtroom audio bed** — gavel knock at the start, soft crowd murmur underneath the whole video
- **Auto-upload** — Selenium controls a real Chrome window to upload directly to YouTube Studio

---

## ⚙️ Requirements

- Windows, macOS, or Linux
- Python 3.9 or newer (3.13 recommended)
- Google Chrome installed
- ffmpeg installed ([download here](https://ffmpeg.org/download.html) — on Windows just add it to PATH)
- A free [Groq API key](https://console.groq.com) (14,400 requests/day free)

> **Note for Windows users:** Use a normal (non-admin) PowerShell window. Running as Administrator causes Chrome to crash.

---

## 🚀 Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/court-chronicles-bot.git
cd court-chronicles-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

If you hit a `urllib3` error, run:

```bash
pip install --upgrade urllib3
```

### 3. Get a free Groq API key

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up (free, no credit card)
3. Go to **API Keys** → **Create API Key**
4. Copy the key (starts with `gsk_`)

Save it to the bot:

```bash
python main.py config --anthropic-key gsk_YOUR_GROQ_KEY_HERE
```

> The config flag is called `--anthropic-key` for historical reasons — just paste your Groq key there.

### 4. Export your YouTube cookies

The bot uploads using your browser session — no Google Cloud account needed.

1. Install the **[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)** Chrome extension
2. Go to [youtube.com](https://youtube.com) while logged into your channel
3. Click the extension icon → select **youtube.com** → **Export**
4. Save the file as `cookies.txt` inside the project folder

> ⚠️ Keep `cookies.txt` private — treat it like a password. Never commit it to GitHub (it's in `.gitignore` already). Re-export if the bot says your session expired.

### 5. Verify everything works

```bash
python main.py check
```

You should see: `OK -- logged in as: Your Channel Name`

---

## 🎬 Usage

### Start the hourly auto-poster

```bash
python main.py start
```

The bot immediately generates and uploads the first video, then repeats every 60 minutes. Leave the terminal open while it runs. A Chrome window will appear for each upload — don't click anything in it.

### Change the posting interval

```bash
python main.py start --interval 30   # every 30 minutes
python main.py start --interval 120  # every 2 hours
```

### Lock to a specific topic

```bash
python main.py start --topic "a defendant who fired their own lawyer mid-trial"
```

Without `--topic` the bot picks a random courtroom scenario each time from a built-in pool of 20 topics.

### Generate a video without uploading (preview)

```bash
python main.py generate
python main.py generate --topic "judge loses it in open court" --output preview.mp4
```

### Upload an existing video manually

```bash
python main.py upload myfile.mp4 --title "Judge Goes VIRAL #Shorts"
```

### View or update your config

```bash
python main.py config
python main.py config --anthropic-key gsk_NEW_KEY
```

---

## 📁 Project structure

```
court-chronicles-bot/
│
├── main.py              ← CLI entry point (start, generate, upload, config, check)
├── generator.py         ← AI script, multi-voice TTS, video renderer
├── cookie_uploader.py   ← Selenium-based YouTube Studio uploader
├── cookie_auth.py       ← Loads cookies.txt and verifies YouTube session
├── scheduler.py         ← Hourly job runner
├── config.py            ← Settings, topic pool, character configuration
├── secret_store.py      ← Encrypted local key storage
│
├── requirements.txt
├── .gitignore
├── README.md
│
├── cookies.txt          ← YOUR session cookies (never commit this)
└── config.json          ← Auto-created after first config command
```

---

## 🎭 Characters & voices

| Character | Voice | Role |
|---|---|---|
| NARRATOR | Aria (US female) | Sets the scene |
| JUDGE | Guy (US male, deep) | Rules the courtroom |
| LAWYER | Christopher (US male) | Plaintiff's attorney |
| KAREN | Jenny (US female) | The defendant |
| DEFENSE | Ryan (British male) | Defense attorney |
| WITNESS | Davis (US male) | Witness on the stand |

All voices are Microsoft Edge TTS — completely free, no account needed, installed via `pip install edge-tts`.

---

## 🖼️ Video layout

```
┌──────────────────────────────┐  ← 340px
│  KAREN DESTROYS $300K CAR    │  Pinned hook title (yellow Impact font)
│        IN OPEN GARAGE        │  Blurred courtroom bokeh background
├──────────────────────────────┤
│                              │  ← 580px
│   [AI courtroom image]       │  Pollinations.ai image with slow Ken Burns zoom
│   photorealistic, fresh      │
│   every video                │
├──────────────────────────────┤
│  [👨‍⚖️] [👔] [👩] [🧑‍💼]         │  ← 360px
│  JUDGE LAWYER KAREN DEFENSE  │  Animated avatars — bounce + lip-sync when speaking
│                              │
│         "BUTTON!"            │  Word-by-word caption in yellow Impact
└──────────────────────────────┘
████████████░░░░░░░░░░░░░░░░░░  ← Gold progress bar
```

---

## 🔧 Troubleshooting

**`urllib3.packages.six.moves` error**
```bash
pip install --upgrade urllib3
```

**Chrome crashes on startup**
- Open Task Manager and kill any `chrome.exe` or `chromedriver.exe` processes
- Make sure you're using a normal (non-admin) PowerShell window
- Check that Chrome is up to date: `chrome://settings/help`

**`cookies.txt not found`**
- Follow Step 4 in Setup above
- Make sure the file is saved in the same folder as `main.py`

**`invalid x-api-key` / 401 error**
- Your Groq key is wrong or expired — generate a new one at [console.groq.com](https://console.groq.com)
- Run `python main.py config --anthropic-key gsk_NEW_KEY`

**Upload fails / session expired**
- Re-export `cookies.txt` from YouTube while logged in
- Make sure you're logged into the correct channel

**Video renders slowly**
- Normal on CPU — each video takes 2–5 minutes to render
- The bot waits 2 minutes after publishing before closing the dialog, then 5 minutes before closing Chrome — this is intentional

**Edge TTS fails, voices sound the same**
```bash
pip install --upgrade edge-tts
```
If it still fails the bot automatically falls back to gTTS (single voice) and continues.

---

## 📋 Example script output

```
[NARRATOR] A $300,000 Ferrari. One open garage door.
[JUDGE] Ms. Karen, please explain your actions.
[KAREN] The garage was OPEN. I thought it was a showroom!
[LAWYER] Your Honor, she activated a hydraulic lift she did not understand.
[KAREN] That button looked exactly like a light switch!
[DEFENSE] My client has absolutely no mechanical background.
[JUDGE] Three hundred and forty-seven thousand dollars. Guilty. Next case.
```



---

## ⚠️ Disclaimer

This project generates fictional courtroom scenarios for entertainment purposes. All characters and situations are AI-generated and do not represent real people or events. You are responsible for ensuring your content complies with YouTube's Terms of Service and Community Guidelines.

