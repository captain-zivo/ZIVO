from __future__ import annotations

import ast
import os
import re
import time
from pathlib import Path
from typing import Any, Tuple

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "zivo60.py"
SRC = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def node(name: str) -> ast.AST:
    for item in TREE.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
            return item
    raise AssertionError(f"missing function: {name}")


ns: dict[str, Any] = {
    "re": re,
    "Tuple": Tuple,
    "normalize_group_command": lambda value: " ".join(
        str(value or "")
        .replace("\u200c", " ")
        .replace("\u200f", "")
        .replace("\u200e", "")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .split()
    ),
}
ann_terms = next(
    n for n in TREE.body
    if isinstance(n, ast.AnnAssign)
    and isinstance(n.target, ast.Name)
    and n.target.id == "CONTENT_PROFANITY_TERMS"
)
ann_patterns = next(
    n for n in TREE.body
    if isinstance(n, ast.AnnAssign)
    and isinstance(n.target, ast.Name)
    and n.target.id == "CONTENT_PROFANITY_PATTERNS"
)
mod = ast.Module(
    body=[
        ann_terms,
        node("_compile_content_profanity_pattern"),
        ann_patterns,
        node("content_has_profanity"),
        node("speaker_learning_has_profanity"),
        node("lock_text_has_profanity"),
    ],
    type_ignores=[],
)
ast.fix_missing_locations(mod)
exec(compile(mod, str(MAIN), "exec"), ns)

terms = tuple(ns["CONTENT_PROFANITY_TERMS"])
blocked = ns["content_has_profanity"]
speaker_blocked = ns["speaker_learning_has_profanity"]
lock_blocked = ns["lock_text_has_profanity"]

assert len(terms) >= 300, len(terms)
assert len(terms) == len(set(terms)), "duplicate profanity terms"

must_exist = {
    "کص", "کصکش", "کیر", "کون", "مادرجنده", "قحبه", "دیوث", "قرمساق",
    "حرومزاده", "پدر سگ", "گاییدن", "گوه خور", "بیشعور", "بی ناموس",
    "koskesh", "kir", "kooni", "madarjende", "dyoos", "haroomzade",
    "fuck", "motherfucker", "bitch", "cocksucker", "asshole", "shithead",
}
assert not (must_exist - set(terms)), must_exist - set(terms)

# Persian direct + obfuscation / stretching / punctuation / emoji / diacritics.
positive_cases = (
    "کص", "ک ص", "ک.ص", "ک🖕ص", "کـص", "کِص",
    "کیییییر", "ک ی ر", "ک💥ی💥ر", "کیرخور",
    "م ا د ر ج ن د ه", "مادر‌جنده", "مادر جنده",
    "ق ح ب ه", "د ی و ث", "قـرمـسـاق", "حروم زاده",
    "پدر...سگ", "گاییدمت", "گــوه خور", "بــی نــامــوس",
    "کصمغز", "کون گشاد", "عقب‌افتاده",
    # Finglish + leetspeak + separators.
    "koskesh", "k0sk3sh", "k.o.s.k.e.s.h", "k💥o💥s",
    "k1r", "k-i-r", "k00ni", "m4d4rj3nd3", "dy00s",
    "har00mz4d3", "b1n4m00s", "g0h kh0r",
    # English + leetspeak / symbol insertion.
    "fuck", "f.u.c.k", "f💥u💥c💥k", "fuuuuuck", "fck",
    "m0th3rfuck3r", "b1tch", "c0cksuck3r", "4ssh0l3", "sh1th34d", "s3x",
)
for text in positive_cases:
    assert blocked(text), f"missed profanity: {text!r}"
    assert speaker_blocked(text), f"speaker missed profanity: {text!r}"
    assert lock_blocked(text), f"lock missed profanity: {text!r}"

# False-positive safety for ordinary words containing short profanity substrings.
negative_cases = (
    "سلام رفیق", "کسب و کار خوب", "تکون نخور", "کونیاک", "کیران امروز هوا خوبه",
    "cocktail recipe", "sexology research", "shitake mushroom", "class assignment",
)
for text in negative_cases:
    assert not blocked(text), f"false positive: {text!r}"

# Verify one shared detector remains wired to both moderation and speaker learning.
assert "return content_has_profanity(value)" in ast.get_source_segment(SRC, node("speaker_learning_has_profanity"))
assert "return content_has_profanity(text)" in ast.get_source_segment(SRC, node("lock_text_has_profanity"))
assert "SPEAKER_PROFANITY_BLOCKED" in SRC
assert "قفل فحش از فرهنگ گسترده فارسی، فینگلیش و انگلیسی" in SRC
assert "همان Detector مشترک" in SRC

# Hot-path guard: first call builds the combined regex; repeated clean messages
# must use the cached combined pattern rather than N separate searches.
blocked("warmup")
combined = getattr(blocked, "_combined_pattern", None)
assert combined is not None
assert blocked("warmup") is False
start = time.perf_counter()
for _ in range(10000):
    assert not blocked("سلام بچه ها امروز برنامه گروه چیه")
elapsed = time.perf_counter() - start
max_elapsed = float(os.getenv("ZIVO_PROFANITY_TEST_MAX_SECONDS", "6.0"))
assert elapsed < max_elapsed, f"profanity clean-path too slow: {elapsed:.3f}s >= {max_elapsed:.3f}s"

print("CHECK ZIVO60.96.33 PROFANITY GUARD EXPANSION: PASS")
print(f"  unique profanity vocabulary: {len(terms)}")
print("  Persian/Finglish/English + sexual/severe abuse coverage: PASS")
print("  spacing/punctuation/emoji/stretching/diacritics/leetspeak bypasses: PASS")
print("  shared lock + speaker-learning detector: PASS")
print(f"  clean-path cached regex 10000 calls: {elapsed:.3f}s")
