"""
=====================================================================
✅ የቴሌግራም WebApp initData ማረጋገጫ (auth.py)
=====================================================================
- HMAC-SHA256 ፊርማ ማረጋገጫ
- የጊዜ ገደብ (24 ሰዓት)
- ከወደፊት የመጣ initData ውድቅ
=====================================================================
"""
import hmac
import hashlib
import json
import time
import logging
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)

INIT_DATA_MAX_AGE = 86400         # 24 ሰዓት
INIT_DATA_FUTURE_TOLERANCE = 300  # 5 ደቂቃ ለሰዓት ልዩነት


def verify_telegram_init_data(init_data: str, bot_token: str):
    """
    የቴሌግራም WebApp initData ማረጋገጫ።
    ልክ ከሆነ dict ይመልሳል፣ ካልሆነ None።
    """
    if not init_data or not bot_token:
        return None

    try:
        parsed = parse_qs(init_data, keep_blank_values=True)

        if 'hash' not in parsed:
            return None
        received_hash = parsed.pop('hash')[0]

        # ✅ auth_date ማረጋገጫ
        auth_date_str = parsed.get('auth_date', [None])[0]
        if not auth_date_str:
            return None
        try:
            auth_date = int(auth_date_str)
        except (ValueError, TypeError):
            return None

        now = int(time.time())
        # ✅ ከወደፊት የመጣ initData ውድቅ
        if auth_date > now + INIT_DATA_FUTURE_TOLERANCE:
            logger.warning(f"initData from future: {auth_date} vs {now}")
            return None
        # ✅ ያለፈበት initData ውድቅ
        if now - auth_date > INIT_DATA_MAX_AGE:
            logger.info(f"initData expired: {now - auth_date}s old")
            return None

        # ✅ data_check_string መገንባት
        data_check_arr = [f"{k}={v[0]}" for k, v in sorted(parsed.items())]
        data_check_string = "\n".join(data_check_arr)

        # ✅ secret_key = HMAC-SHA256("WebAppData", bot_token)
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.warning("initData hash mismatch")
            return None

        user_json = parsed.get('user', [None])[0]
        if not user_json:
            return None

        return json.loads(user_json)

    except Exception as e:
        logger.error(f"initData verification error: {e}")
        return None
