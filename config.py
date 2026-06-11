"""
config.py -- Configuration & constants for Court Chronicles Bot
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    CONFIG_PATH   = BASE_DIR / "config.json"
    WATERMARK_TEXT = "Court Chronicles"
    THEME_NAME     = "cinematic_dark"

    DEFAULT_DESCRIPTION = (
        "Subscribe for more insane courtroom moments! #shorts #court #viral"
    )
    DEFAULT_TAGS = [
        "shorts", "court", "courtroom", "viral", "law",
        "trial", "crime", "lawyer", "judge", "truecrime",
    ]

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
    def load(cls) -> dict:
        if cls.CONFIG_PATH.exists():
            with open(cls.CONFIG_PATH) as f:
                return json.load(f)
        return {"ANTHROPIC_API_KEY": "", "KLING_API_KEY": "", "HF_API_KEY": ""}

    @classmethod
    def save(cls, cfg: dict):
        with open(cls.CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
