import json
import os
from pathlib import Path


class Config:
    # File locations
    CONFIG_FILE = Path("config.json")
    CONFIG_FILE_ENC = Path("config.json.enc")

    # Upload defaults
    DEFAULT_DESCRIPTION = (
        "Subscribe for more insane courtroom moments! #shorts #court #viral"
    )

    DEFAULT_TAGS = [
        "shorts",
        "court",
        "courtroom",
        "viral",
        "law",
        "trial",
        "crime",
        "lawyer",
        "judge",
        "brainrot",
    ]

    # Visual theme / watermark
    WATERMARK_TEXT = "Court Chronicles"
    THEME_NAME = "cinematic_dark"

    # Courtroom topic pool — each entry seeds one video's subject.
    TOPIC_POOL = [
        "a defendant who fired their lawyer mid-trial and defended themselves",
        "the most insane thing a witness ever said on the stand",
        "a case thrown out because of one ridiculous technicality",
        "a criminal caught because they posted evidence on social media",
        "a lawyer who accidentally incriminated their own client",
        "the wildest excuse a defendant ever gave to a judge",
        "a jury that completely shocked the courtroom with their verdict",
        "a judge who lost their temper and went viral",
        "a case where the victim and the criminal switched roles mid-trial",
        "the shortest trial in history and why it ended so fast",
        "a defendant who tried to escape the courtroom mid-hearing",
        "a confession that came out of nowhere during cross-examination",
        "a case that hinged entirely on a single text message",
        "a mistrial that happened for the most absurd reason imaginable",
        "a defendant who showed up to court in a ridiculous disguise",
        "the dumbest criminal plan that somehow almost worked",
        "a cold case cracked decades later by pure accident",
        "a moment a lawyer accidentally destroyed their own witness",
        "a celebrity court case that everyone has forgotten about",
        "a verdict so surprising the judge had to restore order in the room",
    ]

    @classmethod
    def _normalize(cls, cfg: dict) -> dict:
        return {
            "GROQ_API_KEY": str(cfg.get("GROQ_API_KEY", "")).strip(),
            "WATERMARK_TEXT": str(
                cfg.get("WATERMARK_TEXT", cls.WATERMARK_TEXT)
            ).strip(),
            "THEME_NAME": str(
                cfg.get("THEME_NAME", cls.THEME_NAME)
            ).strip(),
        }

    @classmethod
    def load(cls):
        # Encrypted config wins if both exist -- it's the freshly-written one.
        if cls.CONFIG_FILE_ENC.exists():
            try:
                from secret_store import decrypt_path, get_passphrase
                pp = get_passphrase("BrainRot passphrase: ")
                raw = decrypt_path(cls.CONFIG_FILE_ENC, pp)
                return cls._normalize(json.loads(raw.decode("utf-8")))
            except Exception as e:
                print(f"WARNING: could not decrypt {cls.CONFIG_FILE_ENC}: {e}")
                # Fall through to plaintext / env so the bot doesn't hard-fail.

        if cls.CONFIG_FILE.exists():
            try:
                with open(cls.CONFIG_FILE, "r", encoding="utf-8") as f:
                    return cls._normalize(json.load(f))
            except Exception:
                pass

        api_key = os.getenv("GROQ_API_KEY", "").strip()

        return {
            "GROQ_API_KEY": api_key,
            "WATERMARK_TEXT": cls.WATERMARK_TEXT,
            "THEME_NAME": cls.THEME_NAME,
        }

    @classmethod
    def save(cls, cfg: dict):
        payload = cls._normalize(cfg)

        # If the user has already encrypted their config, keep it encrypted on
        # save (and remove any leftover plaintext).
        if cls.CONFIG_FILE_ENC.exists():
            try:
                from secret_store import encrypt_path, get_passphrase
                pp = get_passphrase("BrainRot passphrase: ")
                tmp = cls.CONFIG_FILE.with_suffix(".json.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                try:
                    encrypt_path(tmp, cls.CONFIG_FILE_ENC, pp)
                finally:
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
                if cls.CONFIG_FILE.exists():
                    try:
                        cls.CONFIG_FILE.unlink()
                    except Exception:
                        pass
                return
            except Exception as e:
                print(f"WARNING: could not write encrypted config ({e}); falling back to plaintext.")

        with open(cls.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
