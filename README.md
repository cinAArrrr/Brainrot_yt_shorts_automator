# Court Chronicles Bot

AI-powered YouTube Shorts auto-poster that generates and uploads dramatic courtroom videos on autopilot.

## How it works

1. **Groq** (free) generates a courtroom dialogue script via Llama 3
2. **Edge-TTS** (free) converts dialogue to multi-character speech
3. **Procedural rendering** draws a courtroom scene with animated character avatars
4. **Selenium** uploads the finished video to YouTube Shorts

No paid APIs required. Fully automated after one-time login.

## Quick start

```bash
pip install -r requirements.txt
python main.py config --groq-key gsk_YOUR_GROQ_KEY
```

Log into YouTube once (saves cookies for future headless runs):

```bash
python main.py login
```

Start the auto-poster:

```bash
python main.py start
```

## Commands

| Command | Description |
|---------|-------------|
| `python main.py login` | Log into YouTube once — saves cookies for headless use |
| `python main.py start` | Start the auto-poster loop (fully headless) |
| `python main.py config --groq-key KEY` | Set your Groq API key |
| `python main.py config` | View current config |
| `python main.py generate --topic "my topic"` | Generate a video without uploading |
| `python main.py upload video.mp4 --title "My Title"` | Upload an existing video |
| `python main.py check` | Verify saved YouTube cookies |

## Getting API keys

- **Groq** (required): https://console.groq.com — free tier: 30 req/min, 14k req/day
- **Hugging Face** (optional): https://huggingface.co/settings/tokens — free AI video backgrounds
- **Kling** (optional): https://klingai.com — paid AI video backgrounds

## YouTube login (one-time)

Instead of manually exporting cookies, just run:

```bash
python main.py login
```

A browser opens, you log into YouTube once, and cookies are saved automatically. Every subsequent run is fully headless. Re-run when cookies expire (months later).

## License

MIT
