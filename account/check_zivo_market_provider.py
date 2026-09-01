#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Network-free checks for the real TGJU market provider."""

from __future__ import annotations

import threading
import time
import urllib.error
from typing import Dict
from unittest.mock import patch

import zivo_social_games as social


def _page(current: int, change: float, clock: str, closings: list[int]) -> bytes:
    rows = []
    for offset, close in enumerate(closings, start=1):
        day = 10 + offset
        rows.append(
            "<tr>"
            f"<td>1405/06/{day:02d}</td>"
            f"<td>{close - 300:,}</td>"
            f"<td>{close - 500:,}</td>"
            f"<td>{close + 500:,}</td>"
            f"<td><span>{close:,}</span></td>"
            f"<td>{change}%</td>"
            "<td>100</td>"
            "</tr>"
        )
    return (
        "<html><body>"
        f'<span data-col="info.last_trade.PDrCotVal">{current:,}</span>'
        f'<span data-col="info.change_percent">{change}</span>'
        f'<span data-col="info.time">{clock}</span>'
        "<table><thead><tr><th>تاریخ</th><th>بازگشایی</th><th>کمترین</th>"
        "<th>بیشترین</th><th>پایانی</th><th>درصد تغییر</th><th>تغییر</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    ).encode("utf-8")


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self.payload if limit < 0 else self.payload[:limit]


def main() -> None:
    pages: Dict[str, bytes] = {
        "price_dollar_rl": _page(1_000_000, 1.25, "12:01", [970_000, 980_000, 990_000]),
        "price_eur": _page(1_100_000, -0.5, "12:02", [1_070_000, 1_080_000, 1_090_000]),
        # One real observation is retained, but must not be called verified
        # chart history because the contract requires at least two points.
        "price_gbp": _page(1_300_000, 0, "12:03", [1_290_000]),
        "geram18": _page(70_000_000, 2.4, "12:04", [68_000_000, 69_000_000, 69_500_000]),
    }
    calls: list[tuple[str, float]] = []
    calls_lock = threading.Lock()

    def fake_urlopen(request, timeout=0):
        url = str(getattr(request, "full_url", request))
        parts = url.rstrip("/").split("/")
        slug = parts[-2] if parts[-1] == "history" else parts[-1]
        with calls_lock:
            calls.append((slug, float(timeout)))
        return _Response(pages[slug])

    original_cache = social._MARKET_SNAPSHOT_CACHE
    original_failure_until = social._MARKET_SNAPSHOT_FAILURE_UNTIL
    try:
        social._MARKET_SNAPSHOT_CACHE = (0.0, {})
        social._MARKET_SNAPSHOT_FAILURE_UNTIL = 0.0
        with patch.object(social.urllib.request, "urlopen", side_effect=fake_urlopen):
            first = social.market_snapshot_data()
            assert {slug for slug, _timeout in calls} == set(pages)
            assert all(timeout == 4 for _slug, timeout in calls)
            assert first["source"].endswith("(TGJU)")
            assert first["usd_toman"] == 100_000
            assert first["eur_toman"] == 110_000
            assert first["gbp_toman"] == 130_000
            assert first["gold_toman"] == 7_000_000
            assert first["quotes"]["usd"]["change_percent"] == 1.25
            assert first["quotes"]["eur"]["change_percent"] == -0.5
            assert first["quotes"]["usd"]["history_verified"] is True
            assert first["quotes"]["gbp"]["history_verified"] is False
            assert len(first["quotes"]["gbp"]["history"]) == 1
            usd_history = first["quotes"]["usd"]["history"]
            assert [point["toman"] for point in usd_history] == [99_000, 98_000, 97_000]
            assert all(point["timestamp"].startswith("1405/06/") for point in usd_history)

            real_layout = (
                "<table><tr><td>2,314,800</td><td>2,306,200</td>"
                "<td>2,345,500</td><td>2,336,100</td><td>85,800</td>"
                "<td>3.81%</td><td>2026/08/23</td><td>1405/06/01</td></tr></table>"
            )
            parsed_real = social._tgju_history_from_page(real_layout)
            assert parsed_real == [{"timestamp": "1405/06/01", "toman": 233_610.0}]

            # The 120-second cache performs no more requests and is protected
            # from caller mutation by deep copies.
            call_count = len(calls)
            first["quotes"]["usd"]["toman"] = -1
            second = social.market_snapshot_data()
            assert len(calls) == call_count
            assert second["quotes"]["usd"]["toman"] == 100_000
            assert second["cache_status"] == "live" and second["stale"] is False

        # Expire the healthy cache.  A failed refresh returns exactly the last
        # healthy market observations and marks them stale; it invents nothing.
        social._MARKET_SNAPSHOT_CACHE = (time.monotonic() - 121, second)
        with patch.object(
            social.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            fallback = social.market_snapshot_data()
        assert fallback["stale"] is True and fallback["cache_status"] == "stale"
        assert "آخرین داده سالم" in fallback["source"]
        assert "آخرین داده سالم" in fallback["quotes"]["usd"]["source"]
        assert fallback["usd_toman"] == second["usd_toman"]
        assert fallback["quotes"]["gold18"]["history"] == second["quotes"]["gold18"]["history"]

        # The failure circuit serves the same explicit stale fallback without
        # touching the network again until its bounded cooldown expires.
        with patch.object(
            social.urllib.request,
            "urlopen",
            side_effect=AssertionError("negative cache unexpectedly hit the network"),
        ) as blocked_urlopen:
            cooldown_fallback = social.market_snapshot_data()
        blocked_urlopen.assert_not_called()
        assert cooldown_fallback["stale"] is True

        # With no previous healthy data, provider failure must stay a failure;
        # no default rate or fabricated chart point may be returned.
        social._MARKET_SNAPSHOT_CACHE = (0.0, {})
        social._MARKET_SNAPSHOT_FAILURE_UNTIL = 0.0
        with patch.object(
            social.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            try:
                social.market_snapshot_data()
            except urllib.error.URLError:
                pass
            else:
                raise AssertionError("offline provider unexpectedly returned fabricated data")

        # A second caller during the negative-cache window fails immediately
        # and does not allocate another four-asset HTTP fan-out.
        with patch.object(
            social.urllib.request,
            "urlopen",
            side_effect=AssertionError("failure cooldown unexpectedly hit the network"),
        ) as blocked_urlopen:
            try:
                social.market_snapshot_data()
            except RuntimeError as exc:
                assert str(exc) == "TGJU_MARKET_FAILURE_COOLDOWN"
            else:
                raise AssertionError("negative cache unexpectedly returned data")
        blocked_urlopen.assert_not_called()

        # Each asset has at most two sequential HTTP waits (history + profile),
        # keeping the provider's 8-second HTTP budget below the async 12-second
        # outer timeout even when every endpoint stalls.
        assert social._MARKET_PROVIDER_HTTP_BUDGET_SECONDS == 8
        attempt_urls: list[str] = []

        def bounded_failure(request, timeout=0):
            attempt_urls.append(str(getattr(request, "full_url", request)))
            if len(attempt_urls) == 1:
                raise urllib.error.URLError("history offline")
            return _Response(b"<html>no market value</html>")

        with patch.object(social.urllib.request, "urlopen", side_effect=bounded_failure):
            try:
                social._tgju_asset("price_dollar_rl")
            except ValueError as exc:
                assert str(exc).startswith("TGJU_VALUE_MISSING:")
            else:
                raise AssertionError("missing provider value unexpectedly succeeded")
        assert len(attempt_urls) == social._MARKET_MAX_HTTP_ATTEMPTS_PER_ASSET == 2
    finally:
        social._MARKET_SNAPSHOT_CACHE = original_cache
        social._MARKET_SNAPSHOT_FAILURE_UNTIL = original_failure_until

    print("CHECK ZIVO MARKET PROVIDER: PASS")


if __name__ == "__main__":
    main()
