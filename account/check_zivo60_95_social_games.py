#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

import zivo_social_games as social
import zivo_speaker as speaker


def set_balance(path: Path, user_id: int, amount: int) -> None:
    now = social._now()
    with closing(sqlite3.connect(path)) as con:
        con.execute(
            "INSERT INTO social_meow_accounts "
            "(user_id,balance,total_earned,total_spent,last_claim_at,created_at,updated_at) "
            "VALUES (?,?,0,0,0,?,?) ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance",
            (int(user_id), int(amount), now, now),
        )
        con.commit()


def get_balance(path: Path, user_id: int) -> int:
    with closing(sqlite3.connect(path)) as con:
        return int(con.execute("SELECT balance FROM social_meow_accounts WHERE user_id=?", (int(user_id),)).fetchone()[0])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zivo95_") as raw:
        db = Path(raw) / "social.db"
        social.configure(db, global_owner_id=9001, bot_user_ids={9999})

        # Parser coverage for every newly routed family.
        assert social.parse_social_command("بازی دوز")["action"] == "ttt_start"
        assert social.parse_social_command("دوز 9")["cell"] == 9
        assert social.parse_social_command("شیپ")["action"] == "ship"
        assert social.parse_social_command("قیمت دلار و طلا")["action"] == "market"
        assert social.parse_social_command("فاصله تهران تا رشت")["destination"] == "رشت"
        assert social.parse_social_command("انتقال میو 50 @test")["amount"] == 50
        assert social.parse_social_command("بازی سر 20")["stake"] == 20
        assert social.parse_social_command("خرید پت سگ هاسکی")["action"] == "pet_buy"
        assert social.parse_social_command("فروش خانه 1 5000")["action"] == "house_list"
        assert speaker.classify_speaker_event("حوصلم سر رفته") == "bored"
        assert speaker.classify_speaker_event("خیلی ناراحتم") == "sad"
        one = speaker.choose_default_response("normal", "hello")
        two = speaker.choose_default_response("normal", "hello")
        assert one != two

        # Claim is globally persisted and rate limited to five minutes.
        first_claim = social.claim_meow(1)
        claimed_balance = social.balance(1)
        assert 10 <= claimed_balance <= 20 and "۵ دقیقه" in first_claim
        second_claim = social.claim_meow(1)
        assert "هنوز وقت" in second_claim and social.balance(1) == claimed_balance

        # Transfer: recipient must have started a bot, 2% tax, atomic one-time confirmation.
        set_balance(db, 1, 200)
        assert "استارت" in social.prepare_transfer(1, 2, 50)
        social.mark_private_started(2, "secondary")
        prepared = social.prepare_transfer(1, 2, 50, "group:77")
        assert "مالیات ۲٪" in prepared and "49 میو" in prepared
        confirmed = social.confirm_transfer(1, "فرستنده")
        assert "موفقیت" in confirmed
        assert get_balance(db, 1) == 150 and get_balance(db, 2) == 49
        assert "وجود نداره" in social.confirm_transfer(1, "فرستنده")
        notifications = social.claim_notifications("secondary", 10)
        assert len(notifications) == 1 and notifications[0]["user_id"] == 2
        social.finish_notification(int(notifications[0]["notification_id"]), True)
        with closing(sqlite3.connect(db)) as con:
            columns = {str(row[1]) for row in con.execute("PRAGMA table_info(social_notifications)")}
        assert "claimed_at" in columns

        # Wager: a 20+20 game awards exactly 36 and burns 4 tax.
        set_balance(db, 10, 100)
        set_balance(db, 20, 100)
        assert "جایزه برنده: 36 میو" in social.create_wager(700, 10, 20, "اول")
        wager_result = social.accept_wager(700, 20, "اول", "دوم")
        assert "نتیجه بازی" in wager_result
        assert get_balance(db, 10) + get_balance(db, 20) == 196

        # Tic-tac-toe accepts only its two players and resolves a deterministic win sequence.
        assert "منتظر بازیکن" in social.tic_tac_toe(55, 10, "اول", "start")
        assert "شروع شد" in social.tic_tac_toe(55, 20, "دوم", "join")
        assert "فقط دو بازیکن" in social.tic_tac_toe(55, 30, "سوم", "move", 3)
        social.tic_tac_toe(55, 10, "اول", "move", 1)
        social.tic_tac_toe(55, 20, "دوم", "move", 4)
        social.tic_tac_toe(55, 10, "اول", "move", 2)
        social.tic_tac_toe(55, 20, "دوم", "move", 5)
        assert "برنده: اول" in social.tic_tac_toe(55, 10, "اول", "move", 3)
        social.tic_tac_toe(56, 10, "قدیمی", "start")
        social._TTT_GAMES[56]["created"] = time.monotonic() - 901
        assert "سازنده: تازه" in social.tic_tac_toe(56, 20, "تازه", "start")

        # Ship draws from active users and never repeats the immediate pair.
        active = [
            {"user_id": 101, "name": "سارا", "username": "sara"},
            {"user_id": 102, "name": "علی", "username": "ali"},
            {"user_id": 103, "name": "مریم", "username": "maryam"},
            {"user_id": 104, "name": "رضا", "username": "reza"},
        ]
        ship1 = social.choose_ship(88, active)
        ship2 = social.choose_ship(88, active)
        pair1 = {item["user_id"] for item in ship1["users"]}
        pair2 = {item["user_id"] for item in ship2["users"]}
        assert len(pair1) == 2 and len(pair2) == 2 and pair1 != pair2
        assert "۱۰۰ پیام اخیر" in ship1["text"]

        # Distance reports both road kilometres and driving time.
        distance = social.distance_text("تهران", "رشت")
        assert "فاصله تقریبی جاده‌ای" in distance and "زمان تقریبی با ماشین" in distance
        synthetic_market = "<h3>نرخ فعلی:: 1,927,000 -</h3>"
        visible_market = " ".join(social.re.sub(r"<[^>]+>", " ", synthetic_market).split())
        match = social.re.search(r"نرخ\s*فعلی\s*:*\s*([0-9,]+)", visible_market)
        assert match and social._numeric(match.group(1)) == 1_927_000

        # Pet catalogue has ten breeds for each of three species; feeding and death are durable.
        assert len(social.PET_CATALOG) == 30
        set_balance(db, 30, 2000)
        assert "هاسکی" in social.buy_pet(30, "سگ هاسکی")
        assert "غذاشو خورد" in social.feed_pet(30)
        assert "شادی" in social.pet_status(30)
        with closing(sqlite3.connect(db)) as con:
            con.execute("UPDATE social_pets SET last_fed_at=0 WHERE user_id=30 AND status='alive'")
            con.commit()
        assert social.expire_hungry_pets() == 1
        assert "هنوز پت زنده‌ای نداری" in social.pet_status(30)

        # Houses can be bought, listed, transferred to another user and reflected in balances.
        set_balance(db, 40, 20000)
        set_balance(db, 50, 20000)
        bought = social.buy_house(40, "teh-zaf")
        assert "شناسه دارایی" in bought
        with closing(sqlite3.connect(db)) as con:
            ownership_id = int(con.execute("SELECT ownership_id FROM social_houses WHERE user_id=40").fetchone()[0])
        listed = social.list_house(40, ownership_id, 7000)
        assert "شماره آگهی" in listed
        with closing(sqlite3.connect(db)) as con:
            listing_id = int(con.execute("SELECT listing_id FROM social_house_listings WHERE seller_id=40").fetchone()[0])
        purchased = social.buy_listed_house(50, listing_id)
        assert "مالک جدید" in purchased
        with closing(sqlite3.connect(db)) as con:
            owner = int(con.execute("SELECT user_id FROM social_houses WHERE ownership_id=?", (ownership_id,)).fetchone()[0])
        assert owner == 50

        source = Path(__file__).with_name("zivo60.py").read_text(encoding="utf-8")
        ai_source = Path(__file__).with_name("zivo_ai_speaker.py").read_text(encoding="utf-8")
        installer_source = Path(__file__).with_name("install_zivo60.sh").read_text(encoding="utf-8")
        assert 'VERSION = "zivo60.95.1"' in source
        for marker in (
            "command_social_group", "command_social_private", "social_notification_delivery_worker",
            "دوز 5", "انتقال میو 50", "فروشگاه پت", "فروشگاه خانه", "فاصله تهران تا رشت",
        ):
            assert marker in source, marker
        assert "_EMOTION_CUES" in ai_source and "_ADVICE_CUES" in ai_source
        assert "colloquial-research-v4" in ai_source
        assert "MIN_DEPLOY_FREE_MB=512" in installer_source
        assert "INSTALL BLOCKED" in installer_source

    print("CHECK ZIVO60.95 SOCIAL GAMES/MEOW/PETS/HOUSES/SPEAKER: PASS")


if __name__ == "__main__":
    main()
