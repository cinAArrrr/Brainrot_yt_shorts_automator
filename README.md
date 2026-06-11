# Court Chronicles Bot

AI-powered YouTube Shorts auto-poster that generates dramatic courtroom videos daily.

## How it works

1. **Groq** (free) generates a courtroom dialogue script via Llama 3
2. **Edge-TTS** (free) converts dialogue to multi-character speech
3. **Procedural rendering** draws a courtroom scene with animated character avatars
4. **Selenium** uploads the finished video to YouTube Shorts

No paid APIs required. All AI services used have generous free tiers.

## Quick start

```bash
pip install -r requirements.txt
```

Set your API keys:

```bash
python main.py config --groq-key gsk_YOUR_GROQ_KEY
```

Export your YouTube cookies (Netscape format) to `cookies.txt`, then:

```bash
python main.py start
```

## Commands

| Command | Description |
|---------|-------------|
| `python main.py config --groq-key KEY` | Set your Groq API key |
| `python main.py config --hf-key KEY` | Set Hugging Face key (optional, for AI video background) |
| `python main.py config` | View current config |
| `python main.py start` | Start the auto-poster loop |
| `python main.py generate --topic "my topic"` | Generate a video without uploading |
| `python main.py upload video.mp4 --title "My Title"` | Upload an existing video |
| `python main.py check` | Verify YouTube cookies work |

## Getting API keys

- **Groq** (required): https://console.groq.com — free tier: 30 req/min
- **Hugging Face** (optional): https://huggingface.co/settings/tokens — free tier: ~1000 req/day
- **Kling** (optional, paid): https://klingai.com — for AI-generated video backgrounds

## Exporting YouTube cookies

1. Install a browser extension like "Get cookies.txt" (chrome/firefox)
2. Log into YouTube in your browser
3. Export cookies as Netscape format
4. Save as `cookies.txt` in the project folder

The bot uses these cookies to authenticate with YouTube Studio for uploads.

## License

MIT
