#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Persian text-to-speech helpers for ZIVO.

Microsoft currently exposes one standard fa-IR female voice (Dilara) and one
standard fa-IR male voice (Farid). The fa-IR voices do not expose native
speaking styles or city accents. The ``style`` profiles below therefore only
make small prosody changes (rate/pitch/volume); they never claim to synthesize
an authentic Tehran or Isfahan accent and never rewrite the user's text.

The original two-argument ``synthesize_persian_voice(text, temp_dir)`` call is
kept intact. New callers can pass ``gender=``, ``style=`` and ``speed=`` keyword
arguments or resolve and persist a :class:`PersianVoiceProfile` themselves.
"""

import asyncio
import os
import re
import shutil
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import edge_tts


PERSIAN_FEMALE_VOICE = "fa-IR-DilaraNeural"
PERSIAN_MALE_VOICE = "fa-IR-FaridNeural"

# These legacy names intentionally remain public and retain their old defaults.
TTS_VOICE = os.getenv("ZIVO_TTS_VOICE", PERSIAN_FEMALE_VOICE).strip() or PERSIAN_FEMALE_VOICE
TTS_FALLBACK_VOICE = os.getenv("ZIVO_TTS_FALLBACK_VOICE", PERSIAN_MALE_VOICE).strip() or PERSIAN_MALE_VOICE
TTS_FEMALE_VOICE = os.getenv("ZIVO_TTS_FEMALE_VOICE", PERSIAN_FEMALE_VOICE).strip() or PERSIAN_FEMALE_VOICE
TTS_MALE_VOICE = os.getenv("ZIVO_TTS_MALE_VOICE", PERSIAN_MALE_VOICE).strip() or PERSIAN_MALE_VOICE
TTS_RATE = os.getenv("ZIVO_TTS_RATE", "+0%").strip() or "+0%"
TTS_VOLUME = os.getenv("ZIVO_TTS_VOLUME", "+0%").strip() or "+0%"
TTS_PITCH = os.getenv("ZIVO_TTS_PITCH", "+0Hz").strip() or "+0Hz"
TTS_MAX_CHARS = max(500, min(4500, int(os.getenv("ZIVO_TTS_MAX_CHARS", "3600"))))
TTS_FFMPEG_TIMEOUT = max(10, min(90, int(os.getenv("ZIVO_TTS_FFMPEG_TIMEOUT", "30"))))


class VoiceProfileError(ValueError):
    """Raised when an unsupported public voice option is requested."""


class UnsupportedPersianAccentError(VoiceProfileError):
    """Raised when a city accent is requested but no real engine voice exists."""


@dataclass(frozen=True)
class PersianVoiceProfile:
    """A resolved, immutable synthesis profile.

    ``native_style`` is deliberately false for the built-in fa-IR voices. The
    named styles are transparent prosody presets, not Azure expressive styles.
    """

    gender: str
    style: str
    accent: str
    primary_voice: str
    fallback_voices: Tuple[str, ...]
    rate: str
    volume: str
    pitch: str
    speed: str = "normal"
    native_style: bool = False

    @property
    def voices(self) -> Tuple[str, ...]:
        return _unique_nonempty((self.primary_voice, *self.fallback_voices))


VOICE_GENDER_LABELS: Dict[str, str] = {
    "auto": "خودکار",
    "female": "زن",
    "male": "مرد",
}
VOICE_STYLE_LABELS: Dict[str, str] = {
    "normal": "عادی",
    "calm": "آرام",
    "energetic": "پرانرژی",
    "formal": "رسمی",
}
VOICE_SPEED_LABELS: Dict[str, str] = {
    "slow": "کند",
    "normal": "عادی",
    "fast": "تند",
}

_GENDER_ALIASES = {
    "": "auto",
    "auto": "auto",
    "default": "auto",
    "خودکار": "auto",
    "پیش فرض": "auto",
    "پیشفرض": "auto",
    "female": "female",
    "woman": "female",
    "زن": "female",
    "خانم": "female",
    "دختر": "female",
    "مونث": "female",
    "مؤنث": "female",
    "male": "male",
    "man": "male",
    "مرد": "male",
    "آقا": "male",
    "اقا": "male",
    "پسر": "male",
    "مذکر": "male",
}

_STYLE_ALIASES = {
    "": "normal",
    "normal": "normal",
    "default": "normal",
    "standard": "normal",
    "عادی": "normal",
    "معمولی": "normal",
    "طبیعی": "normal",
    "روان": "normal",
    "پیش فرض": "normal",
    "پیشفرض": "normal",
    "calm": "calm",
    "soft": "calm",
    "آرام": "calm",
    "ارام": "calm",
    "آروم": "calm",
    "اروم": "calm",
    "ملایم": "calm",
    "energetic": "energetic",
    "lively": "energetic",
    "پرانرژی": "energetic",
    "پر انرژی": "energetic",
    "formal": "formal",
    "serious": "formal",
    "رسمی": "formal",
    "جدی": "formal",
    "معیار": "formal",
}

_SPEED_ALIASES = {
    "": "normal",
    "normal": "normal",
    "default": "normal",
    "عادی": "normal",
    "معمولی": "normal",
    "طبیعی": "normal",
    "روان": "normal",
    "پیش فرض": "normal",
    "پیشفرض": "normal",
    "slow": "slow",
    "کند": "slow",
    "آهسته": "slow",
    "اهسته": "slow",
    "یواش": "slow",
    "fast": "fast",
    "quick": "fast",
    "تند": "fast",
    "سریع": "fast",
}

_STANDARD_ACCENT_ALIASES = {
    "",
    "standard",
    "default",
    "fa ir",
    "persian",
    "iran",
    "ایران",
    "ایرانی",
    "فارسی",
    "فارسی معیار",
    "معیار",
    "استاندارد",
    "پیش فرض",
    "پیشفرض",
}
_UNSUPPORTED_ACCENT_ALIASES = {
    "tehran": "تهرانی",
    "tehrani": "تهرانی",
    "تهران": "تهرانی",
    "تهرانی": "تهرانی",
    "isfahan": "اصفهانی",
    "isfahani": "اصفهانی",
    "esfahan": "اصفهانی",
    "esfahani": "اصفهانی",
    "اصفهان": "اصفهانی",
    "اصفهانی": "اصفهانی",
}


def _normalize_option(value: Optional[str]) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = normalized.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"}))
    normalized = re.sub(r"[\s_-]+", " ", normalized).strip().casefold()
    return normalized


def _unique_nonempty(values: Iterable[str]) -> Tuple[str, ...]:
    result = []
    seen = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return tuple(result)


def _env_voice_fallbacks(name: str) -> Tuple[str, ...]:
    return _unique_nonempty(os.getenv(name, "").split(","))


def normalize_voice_gender(value: Optional[str]) -> str:
    """Return ``auto``, ``female`` or ``male`` from Persian/English aliases."""

    normalized = _normalize_option(value)
    gender = _GENDER_ALIASES.get(normalized)
    if gender is None:
        raise VoiceProfileError("VOICE_GENDER_UNSUPPORTED")
    return gender


def normalize_voice_style(value: Optional[str]) -> str:
    """Return a supported prosody style; these are not native voice styles."""

    normalized = _normalize_option(value)
    style = _STYLE_ALIASES.get(normalized)
    if style is None:
        if normalized in _UNSUPPORTED_ACCENT_ALIASES:
            raise UnsupportedPersianAccentError("PERSIAN_CITY_ACCENT_UNAVAILABLE")
        raise VoiceProfileError("VOICE_STYLE_UNSUPPORTED")
    return style


def normalize_voice_speed(value: Optional[str]) -> str:
    """Return ``slow``, ``normal`` or ``fast`` from Persian/English aliases."""

    normalized = _normalize_option(value)
    speed = _SPEED_ALIASES.get(normalized)
    if speed is None:
        raise VoiceProfileError("VOICE_SPEED_UNSUPPORTED")
    return speed


def normalize_voice_accent(value: Optional[str]) -> str:
    """Accept standard Iranian Persian and reject unavailable city accents."""

    normalized = _normalize_option(value)
    if normalized in _STANDARD_ACCENT_ALIASES:
        return "standard"
    if normalized in _UNSUPPORTED_ACCENT_ALIASES:
        raise UnsupportedPersianAccentError("PERSIAN_CITY_ACCENT_UNAVAILABLE")
    raise VoiceProfileError("VOICE_ACCENT_UNSUPPORTED")


def _rate_with_speed(base_rate: str, speed: str) -> str:
    """Apply the independent speed offset to an Edge percentage rate."""

    if speed == "normal":
        return base_rate
    default_offset = "-15%" if speed == "slow" else "+15%"
    configured = os.getenv(
        f"ZIVO_TTS_SPEED_{speed.upper()}_OFFSET", default_offset
    ).strip() or default_offset
    base_match = re.fullmatch(r"([+-])(\d{1,3})%", str(base_rate).strip())
    offset_match = re.fullmatch(r"([+-])(\d{1,3})%", configured)
    if not offset_match:
        configured = default_offset
        offset_match = re.fullmatch(r"([+-])(\d{1,3})%", configured)
    if not base_match or not offset_match:
        return configured
    base_value = int(base_match.group(2)) * (1 if base_match.group(1) == "+" else -1)
    offset_value = int(offset_match.group(2)) * (1 if offset_match.group(1) == "+" else -1)
    combined = max(-50, min(100, base_value + offset_value))
    return f"{combined:+d}%"


def _style_prosody(style: str, speed: str = "normal") -> Tuple[str, str, str]:
    # Edge TTS supports prosody controls for these voices, but Azure does not
    # list native expressive styles for fa-IR. Keep the adjustments modest.
    defaults = {
        "normal": (TTS_RATE, TTS_VOLUME, TTS_PITCH),
        "calm": ("-8%", "+0%", "-2Hz"),
        "energetic": ("+10%", "+2%", "+2Hz"),
        "formal": ("-4%", "+0%", "-1Hz"),
    }
    rate, volume, pitch = defaults[style]
    env_prefix = f"ZIVO_TTS_STYLE_{style.upper()}"
    selected_rate = os.getenv(f"{env_prefix}_RATE", rate).strip() or rate
    return (
        _rate_with_speed(selected_rate, speed),
        os.getenv(f"{env_prefix}_VOLUME", volume).strip() or volume,
        os.getenv(f"{env_prefix}_PITCH", pitch).strip() or pitch,
    )


def resolve_persian_voice_profile(
    gender: Optional[str] = None,
    style: Optional[str] = None,
    accent: Optional[str] = None,
    speed: Optional[str] = None,
) -> PersianVoiceProfile:
    """Resolve public settings into a synthesis profile.

    Explicit male/female profiles only fall back to voices of the requested
    gender. A wrong-gender fallback would silently violate the group setting.
    The legacy/``auto`` profile retains the historic cross-gender fallback.
    """

    normalized_gender = normalize_voice_gender(gender)
    normalized_style = normalize_voice_style(style)
    normalized_accent = normalize_voice_accent(accent)
    normalized_speed = normalize_voice_speed(speed)
    rate, volume, pitch = _style_prosody(normalized_style, normalized_speed)

    if normalized_gender == "female":
        primary = TTS_FEMALE_VOICE
        fallbacks = _unique_nonempty(
            (*_env_voice_fallbacks("ZIVO_TTS_FEMALE_FALLBACK_VOICES"), PERSIAN_FEMALE_VOICE)
        )
    elif normalized_gender == "male":
        primary = TTS_MALE_VOICE
        fallbacks = _unique_nonempty(
            (*_env_voice_fallbacks("ZIVO_TTS_MALE_FALLBACK_VOICES"), PERSIAN_MALE_VOICE)
        )
    else:
        primary = TTS_VOICE
        fallbacks = _unique_nonempty((TTS_FALLBACK_VOICE,))

    # The property also de-duplicates primary from fallbacks. Doing it here
    # keeps the dataclass easy to inspect and serialize in tests/logs.
    candidates = _unique_nonempty((primary, *fallbacks))
    return PersianVoiceProfile(
        gender=normalized_gender,
        style=normalized_style,
        accent=normalized_accent,
        primary_voice=candidates[0],
        fallback_voices=candidates[1:],
        rate=rate,
        volume=volume,
        pitch=pitch,
        speed=normalized_speed,
        native_style=False,
    )


def persian_voice_capabilities() -> Dict[str, object]:
    """Return stable data suitable for settings/help rendering."""

    return {
        "genders": dict(VOICE_GENDER_LABELS),
        "styles": dict(VOICE_STYLE_LABELS),
        "speeds": dict(VOICE_SPEED_LABELS),
        "accents": {"standard": "فارسی معیار ایران"},
        "native_styles": False,
        "city_accents": False,
        "voices": {
            "female": PERSIAN_FEMALE_VOICE,
            "male": PERSIAN_MALE_VOICE,
        },
    }


def spoken_text_from_message(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or "━" in stripped:
            continue
        if stripped.startswith(("😂 ZIVO", "📖 ZIVO", "🔮 ZIVO", "🎯 ZIVO", "🧠 ZIVO", "💡 ZIVO")):
            continue
        if stripped.startswith("✨ فال برای سرگرمی"):
            continue
        if stripped.startswith("برای دیدن پاسخ بنویس"):
            continue
        lines.append(stripped)
    body = "\n".join(lines).strip()
    body = re.sub(r"https?://\S+", "", body)
    body = re.sub(r"[━│└├⌁]", " ", body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) > TTS_MAX_CHARS:
        body = body[:TTS_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return body


async def _save_with_voice(
    text: str,
    voice: str,
    output_path: Path,
    *,
    rate: Optional[str] = None,
    volume: Optional[str] = None,
    pitch: Optional[str] = None,
) -> None:
    communicate = edge_tts.Communicate(
        text,
        voice=voice,
        rate=rate or TTS_RATE,
        volume=volume or TTS_VOLUME,
        pitch=pitch or TTS_PITCH,
    )
    save = getattr(communicate, "save", None)
    if callable(save):
        await save(str(output_path))
        return
    with output_path.open("wb") as handle:
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                handle.write(chunk.get("data", b""))


async def _convert_mp3_to_voice_ogg(source: Path, target: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False

    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "-vbr",
            "on",
            "-application",
            "voip",
            str(target),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, _stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=TTS_FFMPEG_TIMEOUT,
        )
        if process.returncode != 0:
            return False
        return target.is_file() and target.stat().st_size > 512
    except asyncio.TimeoutError:
        if process is not None and process.returncode is None:
            process.kill()
            try:
                await process.wait()
            except Exception:
                pass
        return False
    except Exception:
        return False


def _remove_outputs(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


async def synthesize_persian_voice(
    text: str,
    temp_dir: Path,
    *,
    gender: Optional[str] = None,
    style: Optional[str] = None,
    accent: Optional[str] = None,
    speed: Optional[str] = None,
    profile: Optional[PersianVoiceProfile] = None,
) -> Optional[Path]:
    """Synthesize Persian speech while preserving the legacy call contract.

    When ``profile`` is supplied, gender/style/accent/speed must be omitted so a
    caller cannot accidentally persist one setting but synthesize another.
    """

    spoken = spoken_text_from_message(text)
    if len(spoken) < 2:
        return None

    if profile is not None and any(value is not None for value in (gender, style, accent, speed)):
        raise VoiceProfileError("VOICE_PROFILE_CONFLICT")
    selected = profile or resolve_persian_voice_profile(gender, style, accent, speed)
    if not isinstance(selected, PersianVoiceProfile) or not selected.voices:
        raise VoiceProfileError("VOICE_PROFILE_INVALID")

    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    mp3_output = temp_dir / f"zivo_voice_{token}.mp3"
    ogg_output = temp_dir / f"zivo_voice_{token}.ogg"
    last_error: Optional[Exception] = None

    for voice in selected.voices:
        _remove_outputs(mp3_output, ogg_output)
        try:
            await _save_with_voice(
                spoken,
                voice,
                mp3_output,
                rate=selected.rate,
                volume=selected.volume,
                pitch=selected.pitch,
            )
            if not mp3_output.is_file() or mp3_output.stat().st_size <= 1024:
                raise RuntimeError("TTS_OUTPUT_INVALID")
            if await _convert_mp3_to_voice_ogg(mp3_output, ogg_output):
                _remove_outputs(mp3_output)
                return ogg_output
            # ffmpeg is optional: the caller already has a resilient MP3 send
            # fallback, so a valid synthesis should not be discarded.
            _remove_outputs(ogg_output)
            return mp3_output
        except Exception as exc:
            last_error = exc
            _remove_outputs(mp3_output, ogg_output)

    if last_error is not None:
        raise last_error
    return None
