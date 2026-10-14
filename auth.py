"""
=====================================================================
✅ የቴሌግራም WebApp initData ማረጋገጫ (auth.py) - v2.2 FINAL
=====================================================================
✅ HMAC-SHA256 ፊርማ ማረጋገጫ
✅ Constant-time comparison (Timing Attack መከላከል)
✅ የጊዜ ገደብ (24 ሰዓት)
✅ ከወደፊት የመጣ initData ውድቅ
✅ የተደጋገሙ query parameters ውድቅ
✅ የ hash ቅርጽ ማረጋገጫ (hex)
✅ የ user id ማረጋገጫ
✅ ጠንካራ error handling
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
HEX_CHARS = set("0123456789abcdefABCDEF")


def verify_telegram_init_data(init_data: str, bot_token: str):
    """
    የቴሌግራም WebApp initData ማረጋገጫ።

    Args:
        init_data: ከ Telegram.WebApp.initData የሚመጣ ሕብረቁምፊ
        bot_token: የቴሌግራም ቦት ቶከን

    Returns:
        dict: የተረጋገጠ የተጠቃሚ መረጃ (id, first_name, username, ...)
        None: ማረጋገጫው ካልተሳካ
    """
    # ✅ የግቤት ማረጋገጫ
    if not init_data or not bot_token:
        logger.warning("Missing init_data or bot_token")
        return None

    if not isinstance(init_data, str) or not isinstance(bot_token, str):
        logger.warning("Invalid input types")
        return None

    try:
        # ✅ የ query string መተንተን
        parsed = parse_qs(init_data, keep_blank_values=True)

        # ✅ የተደጋገሙ query keys ውድቅ አድርግ
        if any(len(values) != 1 for values in parsed.values()):
            logger.warning("Duplicate init_data parameters detected")
            return None

        # ✅ hash መኖሩን ማረጋገጥ
        if 'hash' not in parsed:
            logger.warning("No hash in init_data")
            return None

        received_hash = parsed.pop('hash')[0]

        # ✅ የ hash ቅርጽ ማረጋገጫ — 64 hex characters
        if (
            len(received_hash) != 64
            or any(c not in HEX_CHARS for c in received_hash)
        ):
            logger.warning("Invalid hash format")
            return None

        # ✅ auth_date ማረጋገጫ
        auth_date_str = parsed.get('auth_date', [None])[0]
        if not auth_date_str:
            logger.warning("No auth_date")
            return None

        try:
            auth_date = int(auth_date_str)
        except (ValueError, TypeError):
            logger.warning("Invalid auth_date format")
            return None

        now = int(time.time())

        # ✅ ከወደፊት የመጣ initData ውድቅ
        if auth_date > now + INIT_DATA_FUTURE_TOLERANCE:
            logger.warning(f"initData from future: {auth_date} vs {now}")
            return None

        # ✅ ያለፈበት initData ውድቅ
        age = now - auth_date
        if age > INIT_DATA_MAX_AGE:
            logger.info(f"initData expired: {age}s old")
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

        # ✅ calculated_hash = HMAC-SHA256(secret_key, data_check_string)
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        # ✅ Constant-time comparison
        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.warning("initData hash mismatch")
            return None

        # ✅ user JSON ማውጣት
        user_json = parsed.get('user', [None])[0]
        if not user_json:
            logger.warning("No user in init_data")
            return None

        user = json.loads(user_json)

        # ✅ id መኖሩን ማረጋገጥ
        if not isinstance(user, dict) or 'id' not in user:
            logger.warning("Invalid user object")
            return None

        # ✅ የ id ዓይነት ማረጋገጥ
        try:
            user_id = int(user['id'])
            if user_id <= 0:
                logger.warning("Invalid user id")
                return None
        except (ValueError, TypeError):
            logger.warning("User id is not a valid integer")
            return None

        return user

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return None
    except Exception as e:
        logger.error(f"initData verification error: {e}")
        return None
