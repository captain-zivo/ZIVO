#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Safe calculator, market conversion, and PNG cards for ZIVO.

This module deliberately has no dependency on ``zivo60.py`` or
``zivo_social_games.py``.  Network access is also kept out of this layer: the
caller injects a current market snapshot obtained from its trusted provider.

The card renderer treats price history as verified only when the provider sets
``history_verified=True``.  It never invents candles or interpolation points.
Pillow is optional; callers always receive a useful Persian text fallback.
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, DivisionByZero, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union


_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
_OPERATOR_TRANSLATION = str.maketrans(
    {
        "×": "*",
        "÷": "/",
        "−": "-",
        "–": "-",
        "—": "-",
        "＋": "+",
        "／": "/",
    }
)
_PRETTY_OPERATORS = {"*": "×", "/": "÷", "+": "+", "-": "−"}

MAX_EXPRESSION_LENGTH = 256
MAX_EXPRESSION_TOKENS = 128
MAX_EXPRESSION_DEPTH = 32
MAX_NUMBER_DIGITS = 60
MAX_ABSOLUTE_RESULT = Decimal("1e100")
MAX_CONVERSION_AMOUNT = Decimal("1e12")


class ArithmeticSyntaxError(ValueError):
    """Raised when a calculator expression is invalid or outside safe limits."""


class MarketDataError(ValueError):
    """Raised when an injected market snapshot has no usable current data."""


@dataclass(frozen=True)
class ArithmeticResult:
    """A normalized expression and its exact/high-precision decimal result."""

    expression: str
    result: str
    value: Decimal = field(repr=False)

    def as_dict(self) -> Dict[str, str]:
        return {"expression": self.expression, "result": self.result}

    def response_text(self) -> str:
        return (
            "🧮 ZIVO | ماشین‌حساب\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"صورت مسئله: {self.expression}\n"
            f"پاسخ: {self.result}"
        )


@dataclass(frozen=True)
class ConversionRequest:
    asset: str
    amount: Decimal
    amount_text: str
    original_text: str


@dataclass(frozen=True)
class MarketPoint:
    """One provider-supplied history observation; no points are synthesized."""

    timestamp: str
    toman: Decimal


@dataclass(frozen=True)
class MarketQuote:
    asset: str
    label_fa: str
    label_en: str
    unit_fa: str
    unit_en: str
    toman_per_unit: Decimal
    change_percent: Optional[Decimal] = None
    history: Tuple[MarketPoint, ...] = ()
    history_verified: bool = False
    source: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class MarketSnapshot:
    quotes: Mapping[str, MarketQuote]
    source: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class MarketCardResult:
    """Result of card generation. ``image_path`` is ``None`` on fallback."""

    image_path: Optional[Path]
    text: str
    reason: str = ""
    used_verified_history: bool = False
    language: str = "text"

    @property
    def has_image(self) -> bool:
        return self.image_path is not None


_ASSET_META: Dict[str, Dict[str, Any]] = {
    "usd": {
        "label_fa": "دلار آزاد",
        "label_en": "US DOLLAR",
        "unit_fa": "دلار",
        "unit_en": "USD",
        "aliases": ("دلار آمریکا", "دلار امريکا", "دلار", "usd", "us dollar"),
    },
    "eur": {
        "label_fa": "یورو",
        "label_en": "EURO",
        "unit_fa": "یورو",
        "unit_en": "EUR",
        "aliases": ("یورو", "يورو", "یرو", "يورو", "eur", "euro"),
    },
    "gbp": {
        "label_fa": "پوند انگلیس",
        "label_en": "BRITISH POUND",
        "unit_fa": "پوند",
        "unit_en": "GBP",
        "aliases": ("پوند انگلیس", "پوند انگليس", "پوند", "gbp", "british pound", "pound"),
    },
    "gold18": {
        "label_fa": "طلای ۱۸ عیار",
        "label_en": "18K GOLD",
        "unit_fa": "گرم طلای ۱۸ عیار",
        "unit_en": "GRAM",
        "aliases": (
            "گرم طلای 18 عیار",
            "گرم طلا 18 عیار",
            "طلای 18 عیار",
            "طلا 18 عیار",
            "گرم طلا",
            "طلا",
            "gold18",
            "18k gold",
            "gold",
        ),
    },
}

_ASSET_KEY_ALIASES = {
    "usd": "usd",
    "dollar": "usd",
    "eur": "eur",
    "euro": "eur",
    "gbp": "gbp",
    "pound": "gbp",
    "gold": "gold18",
    "gold18": "gold18",
    "geram18": "gold18",
}


def normalize_text(value: Any) -> str:
    """Normalize Persian/Arabic digits and common Arabic letter variants."""

    text = str(value or "")
    text = text.translate(_DIGIT_TRANSLATION).translate(_OPERATOR_TRANSLATION)
    text = text.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    return " ".join(text.strip().split())


def _normalize_number_token(value: Any, *, allow_percent: bool = False) -> str:
    raw = normalize_text(value).strip()
    if allow_percent:
        raw = raw.replace("٪", "").replace("%", "").strip()
    raw = raw.replace("٫", ".")
    if not raw:
        raise ValueError("EMPTY_NUMBER")

    sign = ""
    if raw[:1] in {"+", "-"}:
        sign, raw = raw[0], raw[1:]
    if not raw:
        raise ValueError("EMPTY_NUMBER")

    if "," in raw or "٬" in raw:
        grouped = raw.replace("٬", ",")
        integer, dot, fraction = grouped.partition(".")
        groups = integer.split(",")
        if not (
            1 <= len(groups[0]) <= 3
            and groups[0].isdigit()
            and all(len(group) == 3 and group.isdigit() for group in groups[1:])
        ):
            raise ValueError("INVALID_THOUSANDS_GROUPING")
        raw = "".join(groups) + (dot + fraction if dot else "")
    if not re.fullmatch(r"(?:\d+(?:\.\d+)?|\.\d+)", raw):
        raise ValueError("INVALID_NUMBER")
    digits = sum(char.isdigit() for char in raw)
    if digits > MAX_NUMBER_DIGITS:
        raise ValueError("NUMBER_TOO_LONG")
    return sign + ("0" + raw if raw.startswith(".") else raw)


def _to_decimal(value: Any, *, allow_percent: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("INVALID_NUMBER")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NON_FINITE_NUMBER")
        result = Decimal(str(value))
    else:
        result = Decimal(_normalize_number_token(value, allow_percent=allow_percent))
    if not result.is_finite():
        raise ValueError("NON_FINITE_NUMBER")
    return result


_CALCULATOR_TOKEN_RE = re.compile(
    r"(?:\d{1,3}(?:[,٬]\d{3})+(?:[.٫]\d+)?|\d+(?:[.٫]\d+)?|[.٫]\d+|[()+\-*/])"
)


def _tokenize_expression(text: Any) -> List[Tuple[str, str]]:
    normalized = normalize_text(text)
    if not normalized:
        raise ArithmeticSyntaxError("عبارت خالی است.")
    if len(normalized) > MAX_EXPRESSION_LENGTH:
        raise ArithmeticSyntaxError("عبارت بیش از حد طولانی است.")

    compact = re.sub(r"\s+", "", normalized)
    tokens: List[Tuple[str, str]] = []
    position = 0
    while position < len(compact):
        match = _CALCULATOR_TOKEN_RE.match(compact, position)
        if match is None:
            raise ArithmeticSyntaxError("فقط عدد، پرانتز و عملگرهای + − × ÷ مجازند.")
        raw = match.group(0)
        if raw in {"+", "-", "*", "/", "(", ")"}:
            tokens.append((raw, raw))
        else:
            try:
                canonical = _normalize_number_token(raw)
            except (ValueError, InvalidOperation) as exc:
                raise ArithmeticSyntaxError("قالب عدد معتبر نیست.") from exc
            tokens.append(("number", canonical))
        position = match.end()
        if len(tokens) > MAX_EXPRESSION_TOKENS:
            raise ArithmeticSyntaxError("تعداد اجزای عبارت بیش از حد مجاز است.")
    return tokens


class _DecimalParser:
    def __init__(self, tokens: Sequence[Tuple[str, str]]) -> None:
        self.tokens = list(tokens)
        self.position = 0
        self.depth = 0
        self.binary_operators = 0

    def parse(self) -> Decimal:
        with localcontext() as context:
            # Preserve every accepted operand digit.  The tokenizer permits up
            # to MAX_NUMBER_DIGITS per literal, so a 50-digit context silently
            # rounded otherwise-valid 60-digit integer arithmetic.
            context.prec = max(128, (MAX_NUMBER_DIGITS * 2) + 8)
            value = self._expression()
        if self.position != len(self.tokens):
            raise ArithmeticSyntaxError("ساختار عبارت معتبر نیست.")
        if self.binary_operators == 0:
            raise ArithmeticSyntaxError("حداقل یک عملگر محاسباتی لازم است.")
        return self._guard(value)

    def _current(self) -> Optional[Tuple[str, str]]:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _accept(self, token_type: str) -> bool:
        current = self._current()
        if current and current[0] == token_type:
            self.position += 1
            return True
        return False

    def _expression(self) -> Decimal:
        value = self._term()
        while True:
            if self._accept("+"):
                self.binary_operators += 1
                value = self._guard(value + self._term())
            elif self._accept("-"):
                self.binary_operators += 1
                value = self._guard(value - self._term())
            else:
                return value

    def _term(self) -> Decimal:
        value = self._factor()
        while True:
            if self._accept("*"):
                self.binary_operators += 1
                value = self._guard(value * self._factor())
            elif self._accept("/"):
                self.binary_operators += 1
                denominator = self._factor()
                if denominator == 0:
                    raise ArithmeticSyntaxError("تقسیم بر صفر ممکن نیست.")
                try:
                    value = self._guard(value / denominator)
                except (DivisionByZero, InvalidOperation) as exc:
                    raise ArithmeticSyntaxError("تقسیم معتبر نیست.") from exc
            else:
                return value

    def _factor(self) -> Decimal:
        if self._accept("+"):
            return self._factor()
        if self._accept("-"):
            return self._guard(-self._factor())
        if self._accept("("):
            self.depth += 1
            if self.depth > MAX_EXPRESSION_DEPTH:
                raise ArithmeticSyntaxError("تعداد پرانتزها بیش از حد مجاز است.")
            value = self._expression()
            if not self._accept(")"):
                raise ArithmeticSyntaxError("پرانتز بسته جا افتاده است.")
            self.depth -= 1
            return value
        current = self._current()
        if current and current[0] == "number":
            self.position += 1
            return self._guard(Decimal(current[1]))
        raise ArithmeticSyntaxError("عدد یا پرانتز در جای درست قرار نگرفته است.")

    @staticmethod
    def _guard(value: Decimal) -> Decimal:
        if not value.is_finite() or abs(value) > MAX_ABSOLUTE_RESULT:
            raise ArithmeticSyntaxError("حاصل محاسبه خارج از محدوده امن است.")
        return value


def _pretty_expression(tokens: Sequence[Tuple[str, str]]) -> str:
    pieces: List[str] = []
    for token_type, value in tokens:
        if token_type == "number":
            pieces.append(_format_decimal(Decimal(value), max_fraction=18, grouping=False))
        elif token_type in _PRETTY_OPERATORS:
            pieces.append(_PRETTY_OPERATORS[token_type])
        else:
            pieces.append(value)
    rendered = " ".join(pieces).replace("( ", "(").replace(" )", ")")
    return rendered


def _format_decimal(value: Decimal, *, max_fraction: int = 12, grouping: bool = True) -> str:
    if not value.is_finite():
        raise ValueError("NON_FINITE_NUMBER")
    with localcontext() as context:
        context.prec = max(120, len(value.as_tuple().digits) + max_fraction + 10)
        if value == value.to_integral_value():
            rendered = format(value.quantize(Decimal(1)), ",f" if grouping else "f")
        elif value != 0 and abs(value) < Decimal(1).scaleb(-max_fraction):
            # Never turn a legitimate tiny result into the incorrect text "0".
            significant_quantum = Decimal(1).scaleb(value.adjusted() - max_fraction)
            rounded = value.quantize(significant_quantum, rounding=ROUND_HALF_UP).normalize()
            rendered = format(rounded, "E")
        else:
            exponent = Decimal(1).scaleb(-max_fraction)
            rounded = value.quantize(exponent, rounding=ROUND_HALF_UP)
            rendered = format(rounded, ",f" if grouping else "f").rstrip("0").rstrip(".")
    return "0" if rendered in {"-0", "+0", ""} else rendered


def calculate_expression(text: Any) -> ArithmeticResult:
    """Safely calculate a basic expression without using ``eval``.

    Persian, Arabic, and English digits are accepted together with ``+ - * /
    × ÷`` and parentheses.  Exponents, names, calls, and all other Python
    syntax are rejected.
    """

    tokens = _tokenize_expression(text)
    try:
        value = _DecimalParser(tokens).parse()
    except ArithmeticSyntaxError:
        raise
    except (ArithmeticError, InvalidOperation, ValueError) as exc:
        raise ArithmeticSyntaxError("محاسبه این عبارت ممکن نیست.") from exc
    return ArithmeticResult(
        expression=_pretty_expression(tokens),
        result=_format_decimal(value),
        value=value,
    )


def try_calculate_expression(text: Any) -> Optional[ArithmeticResult]:
    """Return ``None`` instead of raising when text is not a valid expression."""

    try:
        return calculate_expression(text)
    except (ArithmeticSyntaxError, ValueError, InvalidOperation):
        return None


def arithmetic_response(text: Any) -> Optional[str]:
    result = try_calculate_expression(text)
    return result.response_text() if result else None


_CONVERSION_NUMBER = r"(?:\d{1,3}(?:[,٬]\d{3})+(?:[.٫]\d+)?|\d+(?:[.٫]\d+)?|[.٫]\d+)"


def _alias_pattern(alias: str) -> str:
    return re.escape(normalize_text(alias)).replace(r"\ ", r"\s+")


_CONVERSION_PATTERNS: List[Tuple[str, re.Pattern[str], re.Pattern[str]]] = []
for _asset, _meta in _ASSET_META.items():
    for _alias in sorted(set(_meta["aliases"]), key=len, reverse=True):
        _alias_re = _alias_pattern(_alias)
        _before = re.compile(
            rf"(?<![\w.,٬+\-*/])(?P<amount>{_CONVERSION_NUMBER})\s*(?P<alias>{_alias_re})(?!\w)",
            flags=re.IGNORECASE,
        )
        _after = re.compile(
            rf"(?<!\w)(?P<alias>{_alias_re})\s*(?P<amount>{_CONVERSION_NUMBER})(?![\w.])(?!\s*عیار)",
            flags=re.IGNORECASE,
        )
        _CONVERSION_PATTERNS.append((_asset, _before, _after))


def parse_conversion_request(text: Any) -> Optional[ConversionRequest]:
    """Parse currency/gold quantity in either Persian word order.

    Examples: ``120 دلار``, ``دلار 120``, ``۲.۵ گرم طلا`` and
    ``بگو به تومن یورو ۴۰ چقدر میشه``.
    """

    original = str(text or "").strip()
    normalized = normalize_text(original)
    if not normalized:
        return None
    candidates: List[Tuple[int, int, str, re.Match[str]]] = []
    for asset, before, after in _CONVERSION_PATTERNS:
        for pattern in (before, after):
            match = pattern.search(normalized)
            if match:
                candidates.append((match.start(), -(match.end() - match.start()), asset, match))
    if not candidates:
        return None
    _, _, asset, match = min(candidates, key=lambda item: (item[0], item[1]))
    try:
        amount = _to_decimal(match.group("amount"))
    except (ValueError, InvalidOperation):
        return None
    if amount < 0 or amount > MAX_CONVERSION_AMOUNT:
        return None
    return ConversionRequest(
        asset=asset,
        amount=amount,
        amount_text=_format_decimal(amount, max_fraction=8),
        original_text=original,
    )


def _canonical_asset_key(value: Any) -> str:
    # Flat keys are handled below with their companion change field.  Treating
    # usd_toman as a structured usd quote here would silently lose usd_change.
    raw = str(value or "").strip().lower()
    return _ASSET_KEY_ALIASES.get(raw, raw if raw in _ASSET_META else "")


def _coerce_history(value: Any) -> Tuple[MarketPoint, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    points: List[MarketPoint] = []
    for item in value:
        timestamp: Any = ""
        price: Any = None
        if isinstance(item, MarketPoint):
            timestamp, price = item.timestamp, item.toman
        elif isinstance(item, Mapping):
            timestamp = item.get("timestamp", item.get("time", item.get("at", "")))
            price = item.get("toman", item.get("price_toman", item.get("price")))
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            timestamp, price = item[0], item[1]
        try:
            decimal_price = _to_decimal(price)
        except (ValueError, InvalidOperation):
            continue
        if decimal_price <= 0:
            continue
        points.append(MarketPoint(str(timestamp or ""), decimal_price))
    return tuple(points)


def _strict_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "verified"}


def _quote_from_value(
    asset: str,
    value: Any,
    *,
    snapshot_source: str,
    snapshot_updated: str,
    default_change: Any = None,
) -> Optional[MarketQuote]:
    meta = _ASSET_META[asset]
    source = snapshot_source
    updated = snapshot_updated
    change = default_change
    history: Tuple[MarketPoint, ...] = ()
    history_verified = False
    price: Any = value
    if isinstance(value, MarketQuote):
        return value if value.toman_per_unit > 0 else None
    if isinstance(value, Mapping):
        price = value.get(
            "toman_per_unit",
            value.get("toman", value.get("price_toman", value.get("price"))),
        )
        change = value.get("change_percent", value.get("change", default_change))
        source = str(value.get("source", snapshot_source) or "")
        updated = str(value.get("updated_at", value.get("updated", snapshot_updated)) or "")
        history = _coerce_history(value.get("history"))
        history_verified = _strict_bool(value.get("history_verified", False))
    try:
        price_decimal = _to_decimal(price)
    except (ValueError, InvalidOperation):
        return None
    if price_decimal <= 0:
        return None
    change_decimal: Optional[Decimal]
    try:
        change_decimal = _to_decimal(change, allow_percent=True) if change is not None and str(change).strip() else None
    except (ValueError, InvalidOperation):
        change_decimal = None
    return MarketQuote(
        asset=asset,
        label_fa=str(meta["label_fa"]),
        label_en=str(meta["label_en"]),
        unit_fa=str(meta["unit_fa"]),
        unit_en=str(meta["unit_en"]),
        toman_per_unit=price_decimal,
        change_percent=change_decimal,
        history=history,
        history_verified=history_verified and len(history) >= 2,
        source=source,
        updated_at=updated,
    )


def coerce_market_snapshot(value: Any) -> MarketSnapshot:
    """Accept structured quotes or the existing flat ``*_toman`` schema.

    All prices must already be in toman per unit.  Rial is intentionally not
    guessed or divided by ten here, preventing a silent 10× conversion error.
    """

    if isinstance(value, MarketSnapshot):
        quotes = {key: quote for key, quote in value.quotes.items() if quote.toman_per_unit > 0}
        if not quotes:
            raise MarketDataError("NO_MARKET_DATA")
        return MarketSnapshot(quotes=quotes, source=value.source, updated_at=value.updated_at)
    if not isinstance(value, Mapping):
        raise MarketDataError("NO_MARKET_DATA")

    source = str(value.get("source", "") or "")
    updated = str(value.get("updated_at", value.get("updated", "")) or "")
    raw_quotes = value.get("quotes")
    if not isinstance(raw_quotes, Mapping):
        raw_quotes = value

    quotes: Dict[str, MarketQuote] = {}
    for raw_key, raw_value in raw_quotes.items():
        asset = _canonical_asset_key(raw_key)
        if not asset:
            continue
        quote = _quote_from_value(
            asset,
            raw_value,
            snapshot_source=source,
            snapshot_updated=updated,
        )
        if quote:
            quotes[asset] = quote

    flat_keys = {
        "usd": (("usd_toman",), ("usd_change", "usd_change_percent")),
        "eur": (("eur_toman", "euro_toman"), ("eur_change", "euro_change")),
        "gbp": (("gbp_toman", "pound_toman"), ("gbp_change", "pound_change")),
        "gold18": (("gold_toman", "gold18_toman", "geram18_toman"), ("gold_change", "gold18_change")),
    }
    for asset, (price_keys, change_keys) in flat_keys.items():
        if asset in quotes:
            continue
        price = next((value.get(key) for key in price_keys if value.get(key) is not None), None)
        change = next((value.get(key) for key in change_keys if value.get(key) is not None), None)
        quote = _quote_from_value(
            asset,
            price,
            snapshot_source=source,
            snapshot_updated=updated,
            default_change=change,
        )
        if quote:
            quotes[asset] = quote

    if not quotes:
        raise MarketDataError("NO_MARKET_DATA")
    return MarketSnapshot(quotes=quotes, source=source, updated_at=updated)


SnapshotInput = Union[MarketSnapshot, Mapping[str, Any], Callable[[], Any]]


def _resolve_snapshot(value: SnapshotInput) -> MarketSnapshot:
    try:
        resolved = value() if callable(value) else value
    except Exception as exc:
        raise MarketDataError("MARKET_PROVIDER_UNAVAILABLE") from exc
    return coerce_market_snapshot(resolved)


def _trend_fa(change: Optional[Decimal]) -> str:
    if change is None:
        return "روند: داده موجود نیست"
    if change > 0:
        return f"📈 رشد {abs(change):.2f}٪"
    if change < 0:
        return f"📉 کاهش {abs(change):.2f}٪"
    return "➖ بدون تغییر"


def market_snapshot_text(snapshot: Any) -> str:
    """Create the text response used directly or as the PNG fallback."""

    try:
        current = _resolve_snapshot(snapshot)
    except MarketDataError:
        return "⚠️ دادهٔ معتبر و فعلی بازار در دسترس نیست؛ چند دقیقه دیگر دوباره امتحان کن."

    lines = ["💱 ZIVO MARKET | قیمت بازار", "━━━━━━━━━━━━━━━━━━"]
    icons = {"usd": "💵", "eur": "💶", "gbp": "💷", "gold18": "🥇"}
    for asset in ("usd", "eur", "gbp", "gold18"):
        quote = current.quotes.get(asset)
        if not quote:
            continue
        lines.append(
            f"{icons[asset]} {quote.label_fa} (هر {quote.unit_fa}): "
            f"{_format_decimal(quote.toman_per_unit, max_fraction=2)} تومان"
        )
        lines.append(_trend_fa(quote.change_percent))
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(f"🕒 بروزرسانی: {current.updated_at or 'زمان منبع ثبت نشده'}")
    lines.append(f"📡 منبع: {current.source or 'منبع تزریق‌شدهٔ ربات'}")
    lines.append("قیمت‌ها اطلاع‌رسانی‌اند و باید از منبع زندهٔ انتخاب‌شده دریافت شوند.")
    return "\n".join(lines)


def conversion_text(text: Any, snapshot: SnapshotInput) -> Optional[str]:
    """Convert a recognized asset amount to toman using the injected snapshot."""

    request = parse_conversion_request(text)
    if request is None:
        return None
    meta = _ASSET_META[request.asset]
    try:
        current = _resolve_snapshot(snapshot)
    except MarketDataError:
        return (
            f"⚠️ درخواست تبدیل {request.amount_text} {meta['unit_fa']} شناسایی شد، "
            "اما نرخ معتبر و فعلی بازار در دسترس نیست."
        )
    quote = current.quotes.get(request.asset)
    if quote is None:
        return (
            f"⚠️ نرخ فعلی {meta['label_fa']} در منبع بازار موجود نیست؛ "
            "هیچ نرخ تقریبی یا ساختگی استفاده نشد."
        )

    with localcontext() as context:
        context.prec = 80
        toman = request.amount * quote.toman_per_unit
    if not toman.is_finite() or abs(toman) > Decimal("1e120"):
        return "⚠️ مقدار تبدیل خارج از محدوده امن است."
    source = quote.source or current.source or "منبع تزریق‌شدهٔ ربات"
    updated = quote.updated_at or current.updated_at or "زمان منبع ثبت نشده"
    return (
        "💱 ZIVO | تبدیل به تومان\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"درخواست: {request.amount_text} {quote.unit_fa}\n"
        f"نرخ هر {quote.unit_fa}: {_format_decimal(quote.toman_per_unit, max_fraction=4)} تومان\n"
        f"نتیجه: {request.amount_text} {quote.unit_fa} = {_format_decimal(toman, max_fraction=4)} تومان\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🕒 بروزرسانی: {updated}\n"
        f"📡 منبع: {source}"
    )


def _load_pillow() -> Tuple[Any, Any, Any, Any]:
    from PIL import Image, ImageDraw, ImageFont, features  # type: ignore

    return Image, ImageDraw, ImageFont, features


def _font_candidates(explicit: Optional[Union[str, Path]] = None) -> Iterable[Path]:
    seen: set[str] = set()
    values = [
        explicit,
        os.getenv("ZIVO_MARKET_FONT", ""),
        Path(__file__).with_name("Vazirmatn-Regular.ttf"),
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for raw in values:
        if not raw:
            continue
        path = Path(raw)
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            yield path


def _select_font(ImageFont: Any, size: int, explicit: Optional[Union[str, Path]]) -> Tuple[Any, str]:
    for candidate in _font_candidates(explicit):
        if not candidate.is_file():
            continue
        try:
            return ImageFont.truetype(str(candidate), size=size), str(candidate)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size), "PIL_DEFAULT"
    except TypeError:
        return ImageFont.load_default(), "PIL_DEFAULT"


def _safe_text(draw: Any, xy: Tuple[int, int], text: str, *, font: Any, fill: Any, **kwargs: Any) -> None:
    try:
        draw.text(xy, text, font=font, fill=fill, **kwargs)
    except (TypeError, UnicodeError):
        draw.text(xy, text.encode("ascii", "replace").decode("ascii"), font=font, fill=fill)


def _latin_dynamic_text(value: Any, fallback: str) -> str:
    """Keep cards readable when no Persian-capable font/RTL engine exists."""

    text = str(value or "").strip()
    return text if text and text.isascii() else fallback


def _timestamp_axis_value(value: str, index: int) -> float:
    raw = str(value or "").strip()
    if raw:
        try:
            numeric = float(raw)
            if math.isfinite(numeric):
                return numeric
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError):
            pass
    return float(index)


def _draw_verified_chart(
    draw: Any,
    points: Sequence[MarketPoint],
    box: Tuple[int, int, int, int],
) -> bool:
    if len(points) < 2:
        return False
    values = [float(point.toman) for point in points]
    if any(not math.isfinite(item) or item <= 0 for item in values):
        return False
    x_values = [_timestamp_axis_value(point.timestamp, index) for index, point in enumerate(points)]
    if any(x_values[index] <= x_values[index - 1] for index in range(1, len(x_values))):
        x_values = [float(index) for index in range(len(points))]
    x0, y0, x1, y1 = box
    min_value, max_value = min(values), max(values)
    min_x, max_x = min(x_values), max(x_values)
    if max_x == min_x:
        return False
    padding = max((max_value - min_value) * 0.08, max_value * 0.001)
    low, high = min_value - padding, max_value + padding

    coords: List[Tuple[float, float]] = []
    for x_value, price in zip(x_values, values):
        x = x0 + ((x_value - min_x) / (max_x - min_x)) * (x1 - x0)
        y = y1 - ((price - low) / (high - low)) * (y1 - y0)
        coords.append((x, y))
    for index in range(1, len(coords)):
        color = "#00a978" if values[index] > values[index - 1] else ("#e55353" if values[index] < values[index - 1] else "#78909c")
        draw.line((coords[index - 1], coords[index]), fill=color, width=4)
    last_x, last_y = coords[-1]
    draw.ellipse((last_x - 5, last_y - 5, last_x + 5, last_y + 5), fill="#087f72")
    return True


def render_market_card(
    snapshot: SnapshotInput,
    output_path: Union[str, Path],
    *,
    width: int = 1200,
    height: int = 675,
    font_path: Optional[Union[str, Path]] = None,
) -> MarketCardResult:
    """Render an original green/white market card from injected current data.

    If Pillow, usable data, or file output is unavailable, ``image_path`` is
    ``None`` and ``text`` remains ready to send.  History lines are drawn only
    from provider observations carrying ``history_verified=True``.
    """

    fallback = market_snapshot_text(snapshot)
    try:
        current = _resolve_snapshot(snapshot)
    except MarketDataError as exc:
        return MarketCardResult(None, fallback, reason=str(exc), language="text")
    if not (640 <= int(width) <= 2400 and 420 <= int(height) <= 1600):
        return MarketCardResult(None, fallback, reason="INVALID_CARD_SIZE", language="text")
    try:
        Image, ImageDraw, ImageFont, features = _load_pillow()
    except (ImportError, ModuleNotFoundError):
        return MarketCardResult(None, fallback, reason="PILLOW_UNAVAILABLE", language="text")

    target = Path(output_path)
    temp_name = ""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (int(width), int(height)), "#0a9f7d")
        draw = ImageDraw.Draw(image)
        for y in range(int(height)):
            ratio = y / max(1, int(height) - 1)
            red = int(16 + (5 - 16) * ratio)
            green = int(190 + (119 - 190) * ratio)
            blue = int(146 + (111 - 146) * ratio)
            draw.line((0, y, int(width), y), fill=(red, green, blue))
        for x, y, radius in ((80, 90, 58), (1100, 90, 42), (1140, 600, 86), (45, 610, 35)):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline="#35cfa8", width=3)

        margin = int(width * 0.05)
        top = int(height * 0.055)
        draw.rounded_rectangle(
            (margin, top, width - margin, height - top),
            radius=38,
            fill="#f7fbfa",
            outline="#dcebe7",
            width=3,
        )

        font_probe, selected_path = _select_font(ImageFont, 28, font_path)
        del font_probe
        try:
            raqm = bool(features.check("raqm"))
        except Exception:
            raqm = False
        filename = selected_path.lower()
        arabic_font = any(name in filename for name in ("vazir", "arabic", "tahoma", "segoeui", "arial", "dejavu"))
        language = "fa" if raqm and arabic_font else "en"

        title_font, _ = _select_font(ImageFont, max(26, int(width * 0.032)), selected_path)
        subtitle_font, _ = _select_font(ImageFont, max(14, int(width * 0.014)), selected_path)
        asset_font, _ = _select_font(ImageFont, max(18, int(width * 0.019)), selected_path)
        price_font, _ = _select_font(ImageFont, max(23, int(width * 0.026)), selected_path)
        small_font, _ = _select_font(ImageFont, max(12, int(width * 0.012)), selected_path)

        _safe_text(draw, (margin + 34, top + 25), "ZIVO MARKET", font=title_font, fill="#102a2a")
        _safe_text(
            draw,
            (margin + 36, top + 76),
            "LIVE IRAN MARKET - SOURCE DATA ONLY",
            font=subtitle_font,
            fill="#5d7470",
        )
        if language == "fa":
            updated_display = (current.updated_at or "زمان ثبت نشده")[:52]
            source_display = (current.source or "منبع تزریق‌شدهٔ ربات")[:52]
            footer_line = f"بروزرسانی: {updated_display}   |   منبع: {source_display}"
            footer_kwargs = {"direction": "rtl"}
        else:
            updated_display = _latin_dynamic_text(current.updated_at, "provider timestamp")[:52]
            source_display = _latin_dynamic_text(current.source, "live injected provider")[:52]
            footer_line = f"Updated: {updated_display}   |   Source: {source_display}"
            footer_kwargs = {}
        _safe_text(
            draw,
            (width - margin - 35, top + 42),
            footer_line,
            font=small_font,
            fill="#5d7470",
            anchor="ra",
            **footer_kwargs,
        )

        ordered = [current.quotes[key] for key in ("usd", "eur", "gbp", "gold18") if key in current.quotes]
        card_left = margin + 28
        card_right = width - margin - 28
        grid_top = top + 116
        grid_bottom = height - top - 28
        gap = 18
        columns = 2 if len(ordered) > 1 else 1
        rows = (len(ordered) + columns - 1) // columns
        cell_width = (card_right - card_left - gap * (columns - 1)) // columns
        cell_height = (grid_bottom - grid_top - gap * (rows - 1)) // max(1, rows)
        used_history = False

        for index, quote in enumerate(ordered):
            row, column = divmod(index, columns)
            x0 = card_left + column * (cell_width + gap)
            y0 = grid_top + row * (cell_height + gap)
            x1, y1 = x0 + cell_width, y0 + cell_height
            draw.rounded_rectangle((x0, y0, x1, y1), radius=24, fill="#ffffff", outline="#e0ece9", width=2)

            ticker = quote.unit_en if quote.asset != "gold18" else "GOLD 18K"
            _safe_text(draw, (x0 + 23, y0 + 17), ticker, font=asset_font, fill="#173b38")
            label = quote.label_fa if language == "fa" else quote.label_en
            label_kwargs = {"direction": "rtl"} if language == "fa" else {}
            _safe_text(
                draw,
                (x1 - 22, y0 + 21),
                label,
                font=small_font,
                fill="#71817e",
                anchor="ra",
                **label_kwargs,
            )
            price = _format_decimal(quote.toman_per_unit, max_fraction=2)
            _safe_text(draw, (x0 + 22, y0 + 55), price, font=price_font, fill="#071b1a")
            _safe_text(draw, (x0 + 24, y0 + 94), "TOMAN / UNIT", font=small_font, fill="#71817e")

            if quote.change_percent is None:
                trend_text, trend_color = "CHANGE N/A", "#78909c"
            elif quote.change_percent > 0:
                trend_text, trend_color = f"UP +{abs(quote.change_percent):.2f}%", "#00a978"
            elif quote.change_percent < 0:
                trend_text, trend_color = f"DOWN -{abs(quote.change_percent):.2f}%", "#e55353"
            else:
                trend_text, trend_color = "UNCHANGED 0.00%", "#78909c"
            _safe_text(draw, (x1 - 22, y0 + 72), trend_text, font=asset_font, fill=trend_color, anchor="ra")

            chart_top = y0 + 122
            chart_bottom = y1 - 22
            if chart_bottom - chart_top >= 34 and quote.history_verified and len(quote.history) >= 2:
                draw.line((x0 + 22, chart_bottom, x1 - 22, chart_bottom), fill="#dfe9e7", width=1)
                drawn = _draw_verified_chart(draw, quote.history, (x0 + 22, chart_top, x1 - 22, chart_bottom - 4))
                used_history = used_history or drawn
            elif chart_bottom - chart_top >= 18:
                _safe_text(
                    draw,
                    (x0 + 23, chart_bottom - 17),
                    "NO VERIFIED HISTORY - CHART OMITTED",
                    font=small_font,
                    fill="#9aaba7",
                )

        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.stem}_",
            suffix=".png",
            dir=str(target.parent),
            delete=False,
        ) as handle:
            temp_name = handle.name
        image.save(temp_name, format="PNG", optimize=True)
        os.replace(temp_name, target)
        return MarketCardResult(
            image_path=target,
            text=fallback,
            used_verified_history=used_history,
            language=language,
        )
    except Exception as exc:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except Exception:
                pass
        return MarketCardResult(
            None,
            fallback,
            reason=f"CARD_RENDER_FAILED:{type(exc).__name__}",
            language="text",
        )


__all__ = [
    "ArithmeticResult",
    "ArithmeticSyntaxError",
    "ConversionRequest",
    "MarketCardResult",
    "MarketDataError",
    "MarketPoint",
    "MarketQuote",
    "MarketSnapshot",
    "arithmetic_response",
    "calculate_expression",
    "coerce_market_snapshot",
    "conversion_text",
    "market_snapshot_text",
    "normalize_text",
    "parse_conversion_request",
    "render_market_card",
    "try_calculate_expression",
]
