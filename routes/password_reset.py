from flask import Blueprint, request
from datetime import datetime
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from config import get_db_connection, RESET_SECRET_KEY, RESET_TOKEN_TTL_SECONDS, RESET_FRONTEND_URL
from utils.response import api_response
from utils.validators import validate_request, is_valid_email, is_valid_password

# ✅ NEW: reusable email util (SMTP / provider)
from utils.email_utils import send_email

password_reset_bp = Blueprint("password_reset", __name__)

RESET_SALT = "tfshrms-password-reset"
serializer = URLSafeTimedSerializer(RESET_SECRET_KEY)


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_token(token: str):
    return serializer.loads(token, salt=RESET_SALT, max_age=RESET_TOKEN_TTL_SECONDS)


def _build_reset_email_html(reset_link: str) -> str:
    ttl_minutes = int(int(RESET_TOKEN_TTL_SECONDS) / 60) if RESET_TOKEN_TTL_SECONDS else 15
    return f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.5;">
      <p>Hello,</p>

      <p>You requested to reset your password.</p>

      <p>
        <a href="{reset_link}"
           style="display:inline-block;padding:10px 16px;background:#2563eb;color:#ffffff;
                  text-decoration:none;border-radius:6px;">
          Reset Password
        </a>
      </p>

      <p>This link will expire in <b>{ttl_minutes} minutes</b>.</p>

      <p>If you did not request this, you can safely ignore this email.</p>

      <p>— Transform Solution</p>
    </div>
    """


@password_reset_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data, err = validate_request(required=["user_email"])
    if err:
        return err

    user_email = (data.get("user_email") or "").strip().lower()
    if not is_valid_email(user_email):
        return api_response(400, "Invalid email format")

    # Always same message (security)
    response_data = {"message": "If the email exists, a reset link has been generated"}

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT user_id, user_email, is_active, is_delete, updated_date
            FROM tfs_user
            WHERE user_email=%s
            LIMIT 1
        """, (user_email,))
        user = cursor.fetchone()

        if not user or user.get("is_delete") == 0 or user.get("is_active") != 1:
            return api_response(200, response_data["message"], response_data)

        payload = {
            "user_id": int(user["user_id"]),
            "user_email": user_email,
            "pwd_updated": str(user.get("updated_date") or "")
        }

        token = serializer.dumps(payload, salt=RESET_SALT)
        reset_link = f"{RESET_FRONTEND_URL}?token={token}"

        # ✅ NEW: send email (does not change your current API response logic)
        try:
            subject = "Reset your password"
            html_body = _build_reset_email_html(reset_link)
            send_email(user_email, subject, html_body)
        except Exception as mail_err:
            # Keep behavior unchanged: don't fail the API if email fails.
            # Log it for debugging.
            print(f"[forgot_password] Email send failed for {user_email}: {mail_err}")

        # ✅ Backend-only for now: return token/link so you can test (unchanged)
        response_data.update({"token": token, "reset_link": reset_link})
        return api_response(200, response_data["message"], response_data)

    except Exception as e:
        return api_response(500, f"Failed to generate reset link: {str(e)}")
    finally:
        cursor.close()
        conn.close()


@password_reset_bp.route("/verify-reset-token", methods=["POST"])
def verify_reset_token():
    data, err = validate_request(required=["token"])
    if err:
        return err

    token = (data.get("token") or "").strip()
    if not token:
        return api_response(400, "token is required")

    try:
        payload = _load_token(token)
    except SignatureExpired:
        return api_response(400, "Token expired")
    except BadSignature:
        return api_response(400, "Invalid token")

    user_id = int(payload.get("user_id") or 0)
    user_email = (payload.get("user_email") or "").strip().lower()
    token_pwd_updated = payload.get("pwd_updated") or ""

    if not user_id or not user_email:
        return api_response(400, "Invalid token")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT user_id, is_active, is_delete, updated_date
            FROM tfs_user
            WHERE user_id=%s AND user_email=%s
            LIMIT 1
        """, (user_id, user_email))
        user = cursor.fetchone()

        if not user or user.get("is_delete") == 0 or user.get("is_active") != 1:
            return api_response(400, "Invalid token")

        if str(user.get("updated_date") or "") != token_pwd_updated:
            return api_response(400, "Token expired")

        return api_response(200, "Token is valid", {"user_id": user_id})

    finally:
        cursor.close()
        conn.close()


@password_reset_bp.route("/reset-password", methods=["POST"])
def reset_password():
    data, err = validate_request(required=["token", "new_password"])
    if err:
        return err

    token = (data.get("token") or "").strip()
    new_password = data.get("new_password")

    if not token:
        return api_response(400, "token is required")

    if not is_valid_password(new_password):
        return api_response(400, "Password must be at least 6 characters")

    try:
        payload = _load_token(token)
    except SignatureExpired:
        return api_response(400, "Token expired")
    except BadSignature:
        return api_response(400, "Invalid token")

    user_id = int(payload.get("user_id") or 0)
    user_email = (payload.get("user_email") or "").strip().lower()
    token_pwd_updated = payload.get("pwd_updated") or ""

    if not user_id or not user_email:
        return api_response(400, "Invalid token")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT user_id, is_active, is_delete, updated_date
            FROM tfs_user
            WHERE user_id=%s AND user_email=%s
            LIMIT 1
        """, (user_id, user_email))
        user = cursor.fetchone()

        if not user or user.get("is_delete") == 0 or user.get("is_active") != 1:
            return api_response(400, "Invalid token")

        if str(user.get("updated_date") or "") != token_pwd_updated:
            return api_response(400, "Token expired")

        updated_date = _now_str()

        # NOTE: you currently store plaintext passwords.
        # Later replace new_password with hash_password(new_password)
        cursor.execute("""
            UPDATE tfs_user
            SET user_password=%s, updated_date=%s
            WHERE user_id=%s AND is_delete != 0
        """, (new_password, updated_date, user_id))

        conn.commit()
        return api_response(200, "Password reset successfully")

    except Exception as e:
        conn.rollback()
        return api_response(500, f"Failed to reset password: {str(e)}")
    finally:
        cursor.close()
        conn.close()
