from pathlib import Path
import re
ROOT=Path(__file__).resolve().parent
core=(ROOT/'zivo60.py').read_text(encoding='utf-8')
premium=(ROOT/'zivo_premium.py').read_text(encoding='utf-8')
social=(ROOT/'zivo_social_games.py').read_text(encoding='utf-8')
assert any(f'VERSION = "{v}"' in core for v in ('zivo60.96.49','zivo60.96.50'))
for token in ['official_payment_admin','official_group_customization','welcome_media_path','speaker_learn']:
    assert token in core, token
for token in ['premium_manual_review','manual_receipt_submit','admin_approve_manual','admin_reverse_manual','activation_snapshot_json']:
    assert token in premium, token
assert "status='revoked'" in premium
assert "admin-order-reversal" in premium
assert 'SPEAKER_PROFANITY_BLOCKED' in core
assert 'CHECK(balance >= 0)' in social  # historical create remains, migration below removes it safely
assert 'an administrator may reverse an already-consumed paid Meow gift' in social
print('CHECK ZIVO60.96.49 RECEIPT LEDGER + WELCOME/SPEAKER: PASS')
