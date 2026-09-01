#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Focused offline checks for ZIVO Persian voice profiles and fallbacks."""

import asyncio
import importlib.util
import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "zivo_voice.py"
MAIN_PATH = ROOT / "zivo60.py"


class FakeCommunicate:
    calls = []

    def __init__(self, text, voice, **kwargs):
        self.text = text
        self.voice = voice
        self.kwargs = kwargs
        self.__class__.calls.append((text, voice, dict(kwargs)))

    async def save(self, output_path):
        Path(output_path).write_bytes(b"m" * 2048)


edge_tts_stub = types.ModuleType("edge_tts")
edge_tts_stub.Communicate = FakeCommunicate
sys.modules["edge_tts"] = edge_tts_stub

spec = importlib.util.spec_from_file_location("zivo_voice_profile_test", MODULE_PATH)
voice = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = voice
assert spec and spec.loader
spec.loader.exec_module(voice)


def check_profiles():
    legacy = voice.resolve_persian_voice_profile()
    assert legacy.voices == voice._unique_nonempty((voice.TTS_VOICE, voice.TTS_FALLBACK_VOICE))
    assert legacy.gender == "auto" and legacy.style == "normal" and legacy.speed == "normal"

    female = voice.resolve_persian_voice_profile("خانم", "آرام")
    assert female.gender == "female"
    assert female.primary_voice == "fa-IR-DilaraNeural"
    assert all(candidate == "fa-IR-DilaraNeural" for candidate in female.voices)
    assert female.rate == "-8%" and female.pitch == "-2Hz"
    assert female.native_style is False

    male = voice.resolve_persian_voice_profile("آقا", "پرانرژی")
    assert male.gender == "male"
    assert male.primary_voice == "fa-IR-FaridNeural"
    assert all(candidate == "fa-IR-FaridNeural" for candidate in male.voices)
    assert male.rate == "+10%" and male.pitch == "+2Hz"

    fast_male = voice.resolve_persian_voice_profile("مرد", "روان", speed="سریع")
    assert fast_male.style == "normal" and fast_male.speed == "fast"
    assert fast_male.rate == "+15%"
    slow_formal = voice.resolve_persian_voice_profile("زن", "معیار", speed="آهسته")
    assert slow_formal.style == "formal" and slow_formal.speed == "slow"
    assert slow_formal.rate == "-19%"

    formal = voice.resolve_persian_voice_profile("male", "رسمی", "فارسی معیار")
    assert formal.style == "formal" and formal.accent == "standard"

    capabilities = voice.persian_voice_capabilities()
    assert capabilities["city_accents"] is False
    assert capabilities["native_styles"] is False
    assert capabilities["speeds"] == {"slow": "کند", "normal": "عادی", "fast": "تند"}
    assert capabilities["voices"] == {
        "female": "fa-IR-DilaraNeural",
        "male": "fa-IR-FaridNeural",
    }

    for city in ("تهرانی", "اصفهان", "isfahani"):
        try:
            voice.resolve_persian_voice_profile("زن", city)
        except voice.UnsupportedPersianAccentError as exc:
            assert str(exc) == "PERSIAN_CITY_ACCENT_UNAVAILABLE"
        else:
            raise AssertionError(f"unsupported accent accepted as style: {city}")

    try:
        voice.resolve_persian_voice_profile(accent="تهران")
    except voice.UnsupportedPersianAccentError:
        pass
    else:
        raise AssertionError("unsupported Tehran accent accepted")

    # Text remains the user's text; no synthetic city-accent substitutions.
    sentence = "من می‌خواهم امروز به اصفهان بروم."
    assert voice.spoken_text_from_message(sentence) == sentence


def check_main_voice_settings_contract():
    """Keep the group profile defaults, partial updates and copy path wired."""
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert "gender TEXT NOT NULL DEFAULT 'auto'" in source
    assert 'if row is not None else "auto"' in source
    assert 'profile["gender"] = "auto"' in source
    assert "VALUES (?, COALESCE(?, 'auto'), COALESCE(?, 'normal'), COALESCE(?, 'normal'), ?, ?)" in source
    assert "gender = COALESCE(?, tts_voice_settings.gender)" in source
    assert "style = COALESCE(?, tts_voice_settings.style)" in source
    assert "speed = COALESCE(?, tts_voice_settings.speed)" in source
    assert '"voice": {\n        "tts_voice_settings": ("gender", "style", "speed"),' in source
    assert 'if "voice" in applied_sections:\n        _tts_voice_settings_hot.pop(group_id, None)' in source
    upsert_body = source[source.index("def upsert_tts_voice_settings("):source.index("def reset_tts_voice_settings(")]
    assert "current = get_tts_voice_settings" not in upsert_body


async def check_save_options_and_legacy_call():
    FakeCommunicate.calls.clear()
    original_convert = voice._convert_mp3_to_voice_ogg

    async def no_conversion(_source, _target):
        return False

    voice._convert_mp3_to_voice_ogg = no_conversion
    try:
        with tempfile.TemporaryDirectory() as temp_name:
            output = await voice.synthesize_persian_voice("سلام زیوو", Path(temp_name))
            assert output is not None and output.suffix == ".mp3"
            assert output.stat().st_size == 2048
            assert FakeCommunicate.calls[0][1] == voice.TTS_VOICE
            assert FakeCommunicate.calls[0][2] == {
                "rate": voice.TTS_RATE,
                "volume": voice.TTS_VOLUME,
                "pitch": voice.TTS_PITCH,
            }
    finally:
        voice._convert_mp3_to_voice_ogg = original_convert


async def check_fallback_and_ogg_cleanup():
    calls = []
    original_save = voice._save_with_voice
    original_convert = voice._convert_mp3_to_voice_ogg

    async def fallback_save(_text, selected_voice, output_path, **kwargs):
        calls.append((selected_voice, dict(kwargs)))
        if selected_voice == "broken-voice":
            output_path.write_bytes(b"partial")
            raise RuntimeError("network failure")
        output_path.write_bytes(b"m" * 2048)

    async def successful_conversion(_source, target):
        target.write_bytes(b"o" * 1024)
        return True

    voice._save_with_voice = fallback_save
    voice._convert_mp3_to_voice_ogg = successful_conversion
    profile = voice.PersianVoiceProfile(
        gender="female",
        style="normal",
        accent="standard",
        primary_voice="broken-voice",
        fallback_voices=("working-voice", "working-voice"),
        rate="-3%",
        volume="+1%",
        pitch="+2Hz",
        speed="normal",
    )
    try:
        with tempfile.TemporaryDirectory() as temp_name:
            temp_dir = Path(temp_name)
            output = await voice.synthesize_persian_voice(
                "این مسیر fallback است.", temp_dir, profile=profile
            )
            assert output is not None and output.suffix == ".ogg"
            assert output.stat().st_size == 1024
            assert calls == [
                ("broken-voice", {"rate": "-3%", "volume": "+1%", "pitch": "+2Hz"}),
                ("working-voice", {"rate": "-3%", "volume": "+1%", "pitch": "+2Hz"}),
            ]
            assert not list(temp_dir.glob("*.mp3"))
    finally:
        voice._save_with_voice = original_save
        voice._convert_mp3_to_voice_ogg = original_convert


async def check_failure_cleanup_and_conflict():
    original_save = voice._save_with_voice

    async def always_fail(_text, _selected_voice, output_path, **_kwargs):
        output_path.write_bytes(b"partial")
        raise RuntimeError("offline")

    voice._save_with_voice = always_fail
    try:
        with tempfile.TemporaryDirectory() as temp_name:
            temp_dir = Path(temp_name)
            try:
                await voice.synthesize_persian_voice("سلام", temp_dir, gender="male")
            except RuntimeError as exc:
                assert str(exc) == "offline"
            else:
                raise AssertionError("synthesis failure was swallowed")
            assert not list(temp_dir.glob("zivo_voice_*"))

        profile = voice.resolve_persian_voice_profile("زن")
        try:
            await voice.synthesize_persian_voice(
                "سلام", Path(tempfile.gettempdir()), gender="زن", speed="کند", profile=profile
            )
        except voice.VoiceProfileError as exc:
            assert str(exc) == "VOICE_PROFILE_CONFLICT"
        else:
            raise AssertionError("conflicting profile options were accepted")
    finally:
        voice._save_with_voice = original_save


async def main():
    check_profiles()
    check_main_voice_settings_contract()
    await check_save_options_and_legacy_call()
    await check_fallback_and_ogg_cleanup()
    await check_failure_cleanup_and_conflict()
    print("ZIVO PERSIAN VOICE PROFILE CHECK: PASS")


if __name__ == "__main__":
    asyncio.run(main())
