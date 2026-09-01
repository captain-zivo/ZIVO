#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Focused, network-free checks for zivo_market_tools.py."""

from __future__ import annotations

import hashlib
import tempfile
from decimal import Decimal
from pathlib import Path

import zivo_market_tools as market


def assert_rejected(expression: str) -> None:
    assert market.try_calculate_expression(expression) is None, expression


def main() -> None:
    # Calculator: mixed digit sets, precedence, unary signs, parentheses, and
    # decimal arithmetic all go through the hand-written parser (never eval).
    basic = market.calculate_expression("۱۱×۱۳")
    assert basic.expression == "11 × 13"
    assert basic.result == "143"
    assert basic.as_dict() == {"expression": "11 × 13", "result": "143"}
    assert "صورت مسئله: 11 × 13" in basic.response_text()
    assert market.calculate_expression("(٢ + ۳) * ۴").result == "20"
    assert market.calculate_expression("2*-3 + 10").result == "4"
    assert market.calculate_expression("۰٫۱ + 0.2").value == Decimal("0.3")
    assert market.calculate_expression("۱٬۲۰۰ ÷ ۳").result == "400"
    assert market.calculate_expression("1 / 3").result == "0.333333333333"
    assert market.calculate_expression("0.00000000000000000001 + 0").result == "1E-20"
    sixty_digits = "123456789012345678901234567890123456789012345678901234567890"
    assert market.calculate_expression(f"{sixty_digits} + 1").result.replace(",", "") == (
        "123456789012345678901234567890123456789012345678901234567891"
    )
    for hostile in (
        "__import__('os').system('whoami')",
        "2**8",
        "1/0",
        "1,2 + 3",
        "(2+3",
        "42",
        "9e9 + 1",
        "11*13 دلار",
    ):
        assert_rejected(hostile)

    # Existing flat market payload remains accepted; euro/pound can be added
    # with matching *_toman keys.  All supplied rates are already in toman.
    flat_snapshot = {
        "usd_toman": 90_500,
        "usd_change": "1.25",
        "eur_toman": "98,750",
        "eur_change": "-0.40%",
        "gbp_toman": Decimal("115200"),
        "gbp_change": 0,
        "gold_toman": 6_850_000,
        "gold_change": 2.1,
        "updated": "1405/06/08 13:30",
        "source": "TEST LIVE PROVIDER",
    }
    snapshot = market.coerce_market_snapshot(flat_snapshot)
    assert set(snapshot.quotes) == {"usd", "eur", "gbp", "gold18"}
    assert snapshot.quotes["usd"].toman_per_unit == Decimal("90500")
    assert snapshot.quotes["usd"].change_percent == Decimal("1.25")
    assert snapshot.quotes["eur"].change_percent == Decimal("-0.40")

    # Both word orders, Persian/Arabic digits, conversational filler, and the
    # explicit 18K gram unit are recognized.
    cases = {
        "120 دلار": ("usd", Decimal("120")),
        "دلار ۱۲۰": ("usd", Decimal("120")),
        "بیا بگو به تومن یورو ٤٠ چقدر میشه": ("eur", Decimal("40")),
        "پوند 2.5 به تومان": ("gbp", Decimal("2.5")),
        "۲ گرم طلای ۱۸ عیار چقدر میشه": ("gold18", Decimal("2")),
        "طلا ۰٫۵": ("gold18", Decimal("0.5")),
    }
    for text, expected in cases.items():
        parsed = market.parse_conversion_request(text)
        assert parsed is not None, text
        assert (parsed.asset, parsed.amount) == expected, (text, parsed)
    assert market.parse_conversion_request("قیمت دلار چنده") is None
    assert market.parse_conversion_request("طلا ۱۸ عیار") is None
    assert market.parse_conversion_request("-20 دلار") is None

    conversion = market.conversion_text("120 دلار", flat_snapshot)
    assert conversion is not None
    assert "درخواست: 120 دلار" in conversion
    assert "10,860,000 تومان" in conversion
    assert "TEST LIVE PROVIDER" in conversion
    gold = market.conversion_text("طلا ۰٫۵", flat_snapshot)
    assert gold is not None and "3,425,000 تومان" in gold
    missing = market.conversion_text("20 یورو", {"usd_toman": 90_500})
    assert missing is not None and "هیچ نرخ تقریبی یا ساختگی" in missing
    unavailable = market.conversion_text("دلار 2", lambda: (_ for _ in ()).throw(OSError("offline")))
    assert unavailable is not None and "نرخ معتبر و فعلی" in unavailable

    text_card = market.market_snapshot_text(flat_snapshot)
    assert "دلار آزاد" in text_card and "یورو" in text_card and "طلای ۱۸ عیار" in text_card
    assert "TEST LIVE PROVIDER" in text_card
    assert "دادهٔ معتبر" in market.market_snapshot_text({})

    # The renderer does not draw unverified history.  This test remains useful
    # with or without Pillow because text fallback is part of the API contract.
    structured = {
        "source": "TEST LIVE PROVIDER",
        "updated_at": "2026-08-30T13:30:00+03:30",
        "quotes": {
            "usd": {
                "toman": 90_500,
                "change_percent": 1.25,
                "history_verified": False,
                "history": [
                    {"timestamp": "2026-08-30T12:30:00+03:30", "toman": 90_000},
                    {"timestamp": "2026-08-30T13:30:00+03:30", "toman": 90_500},
                ],
            }
        },
    }
    with tempfile.TemporaryDirectory(prefix="zivo_market_") as raw:
        root = Path(raw)
        unverified_path = root / "unverified.png"
        unverified = market.render_market_card(structured, unverified_path)
        if unverified.has_image:
            assert unverified_path.is_file() and unverified_path.stat().st_size > 2_000
            assert not unverified.used_verified_history
        else:
            assert unverified.reason == "PILLOW_UNAVAILABLE", unverified.reason
            assert "دلار آزاد" in unverified.text

        structured["quotes"]["usd"]["history_verified"] = True
        verified_path = root / "verified.png"
        verified = market.render_market_card(structured, verified_path, font_path=root / "missing-font.ttf")
        if verified.has_image:
            assert verified_path.is_file() and verified_path.stat().st_size > 2_000
            assert verified.used_verified_history
            assert verified.language in {"fa", "en"}
            if unverified.has_image:
                first_hash = hashlib.sha256(unverified_path.read_bytes()).digest()
                second_hash = hashlib.sha256(verified_path.read_bytes()).digest()
                assert first_hash != second_hash

        structured["quotes"]["usd"]["history_verified"] = "false"
        strict_flag = market.coerce_market_snapshot(structured)
        assert not strict_flag.quotes["usd"].history_verified

        empty = market.render_market_card({}, root / "must-not-exist.png")
        assert not empty.has_image and empty.reason == "NO_MARKET_DATA"
        assert not (root / "must-not-exist.png").exists()

        original_loader = market._load_pillow
        try:
            def missing_pillow():
                raise ImportError("test")

            market._load_pillow = missing_pillow
            fallback = market.render_market_card(flat_snapshot, root / "fallback.png")
            assert not fallback.has_image and fallback.reason == "PILLOW_UNAVAILABLE"
            assert "TEST LIVE PROVIDER" in fallback.text
        finally:
            market._load_pillow = original_loader

    print("CHECK ZIVO MARKET TOOLS: PASS")


if __name__ == "__main__":
    main()
