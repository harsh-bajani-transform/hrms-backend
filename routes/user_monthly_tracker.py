# routes/user_monthly_tracker.py

from flask import Blueprint, request
from config import get_db_connection
from utils.response import api_response
from datetime import datetime

user_monthly_tracker_bp = Blueprint("user_monthly_tracker", __name__)

# task_work_tracker.date_time is TEXT like "YYYY-MM-DD HH:MM:SS"
TRACKER_DT = "CAST(twt.date_time AS DATETIME)"
TRACKER_YEAR_MONTH = f"(YEAR({TRACKER_DT})*100 + MONTH({TRACKER_DT}))"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def month_year_to_yyyymm_sql(month_year_col: str) -> str:
    """
    Your DB stores month_year like 'JAN2026', 'DEC2025' (MONYYYY).
    Convert MONYYYY -> integer YYYYMM inside SQL.
    """
    return f"""
    CAST(
      DATE_FORMAT(
        STR_TO_DATE(CONCAT('01-', {month_year_col}), '%d-%b%Y'),
        '%Y%m'
      ) AS UNSIGNED
    )
    """


# working days (distinct dates) from task_work_tracker for that month:
# - if month is current: count days up to CURDATE()
# - if month is past: count full month
# - if month is future: 0
WORKING_DAYS_SQL = f"""
(
  SELECT COUNT(DISTINCT DATE(CAST(twt2.date_time AS DATETIME)))
  FROM task_work_tracker twt2
  WHERE twt2.user_id = umt.user_id
    AND twt2.is_active = 1
    AND DATE(CAST(twt2.date_time AS DATETIME)) >= STR_TO_DATE(CONCAT('01-', umt.month_year), '%d-%b%Y')
    AND DATE(CAST(twt2.date_time AS DATETIME)) <=
      CASE
        WHEN (YEAR(CURDATE())*100 + MONTH(CURDATE())) = {month_year_to_yyyymm_sql("umt.month_year")}
        THEN CURDATE()
        WHEN (YEAR(CURDATE())*100 + MONTH(CURDATE())) > {month_year_to_yyyymm_sql("umt.month_year")}
        THEN LAST_DAY(STR_TO_DATE(CONCAT('01-', umt.month_year), '%d-%b%Y'))
        ELSE DATE_SUB(STR_TO_DATE(CONCAT('01-', umt.month_year), '%d-%b%Y'), INTERVAL 1 DAY)
      END
) AS working_days_till_today
"""


# ---------------------------
# ADD
# ---------------------------
@user_monthly_tracker_bp.route("/add", methods=["POST"])
def add_user_monthly_target():
    data = request.get_json(silent=True) or {}

    if not data.get("user_id"):
        return api_response(400, "user_id is required")
    if not data.get("month_year"):
        return api_response(400, "month_year is required (MONYYYY e.g. JAN2026)")
    if not data.get("monthly_target"):
        return api_response(400, "monthly_target is required")

    user_id = int(data["user_id"])
    month_year = str(data["month_year"]).strip()  # keep as-is (MONYYYY)
    monthly_target = str(data["monthly_target"]).strip()
    created_date = str(data.get("created_date") or now_str())
    working_days = data.get("working_days").strip()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Validate user exists
        cursor.execute(
            """
            SELECT user_id
            FROM tfs_user
            WHERE user_id=%s AND is_active=1
            """,
            (user_id,),
        )
        if not cursor.fetchone():
            return api_response(404, "User not found or inactive")

        # Prevent duplicate active (user + month)
        cursor.execute(
            """
            SELECT user_monthly_tracker_id
            FROM user_monthly_tracker
            WHERE user_id=%s AND month_year=%s AND is_active=1
            """,
            (user_id, month_year),
        )
        if cursor.fetchone():
            return api_response(
                409, "Monthly target already exists for this user and month"
            )

        cursor.execute(
            """
            INSERT INTO user_monthly_tracker
                (user_id, month_year, monthly_target, working_days, is_active, created_date)
            VALUES (%s, %s, %s, %s, 1, %s,)
            """,
            (user_id, month_year, monthly_target, working_days, created_date),
        )
        conn.commit()

        return api_response(
            201,
            "User monthly target added successfully",
            {"user_monthly_tracker_id": cursor.lastrowid},
        )

    except Exception as e:
        conn.rollback()
        return api_response(500, f"Add failed: {str(e)}")
    finally:
        cursor.close()
        conn.close()


# ---------------------------
# UPDATE
# ---------------------------
@user_monthly_tracker_bp.route("/update", methods=["POST"])
def update_user_monthly_target():
    data = request.get_json(silent=True) or {}

    if not data.get("user_monthly_tracker_id"):
        return api_response(400, "user_monthly_tracker_id is required")

    umt_id = int(data["user_monthly_tracker_id"])

    updates = []
    params = []

    if "user_id" in data and data["user_id"] not in [None, ""]:
        updates.append("user_id=%s")
        params.append(int(data["user_id"]))

    if "month_year" in data and data["month_year"] not in [None, ""]:
        updates.append("month_year=%s")
        params.append(str(data["month_year"]).strip())  # keep as-is (MONYYYY)

    if "monthly_target" in data and data["monthly_target"] not in [None, ""]:
        updates.append("monthly_target=%s")
        params.append(str(data["monthly_target"]).strip())
        
    if "working_days" in data and data["working_days"] not in [None, ""]:
        updates.append("working_days=%s")
        params.append(data["working_days"].strip())

    if not updates:
        return api_response(400, "Nothing to update")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Current row
        cursor.execute(
            """
            SELECT user_id, month_year
            FROM user_monthly_tracker
            WHERE user_monthly_tracker_id=%s AND is_active=1
            """,
            (umt_id,),
        )
        current = cursor.fetchone()
        if not current:
            return api_response(404, "Active record not found")

        # Validate user if updating it
        if "user_id" in data and data["user_id"] not in [None, ""]:
            new_user_id = int(data["user_id"])
            cursor.execute(
                """
                SELECT user_id
                FROM tfs_user
                WHERE user_id=%s AND is_active=1
                """,
                (new_user_id,),
            )
            if not cursor.fetchone():
                return api_response(404, "User not found or inactive")

        # Prevent duplicate active (final user_id + final month_year)
        if (
            ("user_id" in data and data["user_id"] not in [None, ""])
            or ("month_year" in data and data["month_year"] not in [None, ""])
        ):
            final_user_id = (
                int(data["user_id"])
                if ("user_id" in data and data["user_id"] not in [None, ""])
                else int(current["user_id"])
            )
            final_month_year = (
                str(data["month_year"]).strip()
                if ("month_year" in data and data["month_year"] not in [None, ""])
                else str(current["month_year"])
            )

            cursor.execute(
                """
                SELECT user_monthly_tracker_id
                FROM user_monthly_tracker
                WHERE user_id=%s AND month_year=%s AND is_active=1
                  AND user_monthly_tracker_id<>%s
                """,
                (final_user_id, final_month_year, umt_id),
            )
            if cursor.fetchone():
                return api_response(
                    409, "Monthly target already exists for this user and month"
                )

        params.append(umt_id)
        query = f"""
            UPDATE user_monthly_tracker
            SET {', '.join(updates)}
            WHERE user_monthly_tracker_id=%s
        """
        cursor.execute(query, tuple(params))
        conn.commit()

        return api_response(200, "User monthly target updated successfully")

    except Exception as e:
        conn.rollback()
        return api_response(500, f"Update failed: {str(e)}")
    finally:
        cursor.close()
        conn.close()


# ---------------------------
# DELETE (SOFT)
# ---------------------------
@user_monthly_tracker_bp.route("/delete", methods=["POST"])
def delete_user_monthly_target():
    data = request.get_json(silent=True) or {}

    if not data.get("user_monthly_tracker_id"):
        return api_response(400, "user_monthly_tracker_id is required")

    umt_id = int(data["user_monthly_tracker_id"])

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            UPDATE user_monthly_tracker
            SET is_active=0
            WHERE user_monthly_tracker_id=%s AND is_active=1
            """,
            (umt_id,),
        )
        conn.commit()

        if cursor.rowcount == 0:
            return api_response(404, "Active record not found")

        return api_response(200, "User monthly target deleted successfully")

    except Exception as e:
        conn.rollback()
        return api_response(500, f"Delete failed: {str(e)}")
    finally:
        cursor.close()
        conn.close()


# ---------------------------
# LIST (returns month-wise production sums + working days till today)
# ---------------------------
@user_monthly_tracker_bp.route("/list", methods=["POST"])
def list_user_monthly_targets():
    data = request.get_json(silent=True) or {}

    where_sql = "WHERE umt.is_active=1"
    params = []

    if data.get("user_id"):
        where_sql += " AND umt.user_id=%s"
        params.append(int(data["user_id"]))

    if data.get("month_year"):
        where_sql += " AND umt.month_year=%s"
        params.append(str(data["month_year"]).strip())  # MONYYYY

    query = f"""
        SELECT
            umt.user_monthly_tracker_id,
            umt.user_id,
            u.user_name,
            umt.month_year,
            umt.monthly_target,
            umt.working_days,
            umt.created_date,
            umt.is_active,

            COALESCE(SUM(twt.production), 0) AS total_production,
            COALESCE(SUM(twt.billable_hours), 0) AS total_billable_hours,
            COUNT(twt.tracker_id) AS tracker_rows,

            {WORKING_DAYS_SQL}

        FROM user_monthly_tracker umt
        LEFT JOIN tfs_user u ON u.user_id = umt.user_id

        LEFT JOIN task_work_tracker twt
          ON twt.user_id = umt.user_id
         AND twt.is_active = 1
         AND {TRACKER_YEAR_MONTH} = {month_year_to_yyyymm_sql("umt.month_year")}

        {where_sql}
        GROUP BY umt.user_monthly_tracker_id
        ORDER BY umt.month_year DESC, umt.user_monthly_tracker_id DESC
    """

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        return api_response(200, "User monthly targets fetched successfully", rows)

    except Exception as e:
        return api_response(500, f"List failed: {str(e)}")
    finally:
        cursor.close()
        conn.close()


# ---------------------------
# VIEW (single record + month-wise production sum + working days till today)
# ---------------------------
@user_monthly_tracker_bp.route("/view", methods=["POST"])
def view_user_monthly_target():
    data = request.get_json(silent=True) or {}

    if not data.get("user_monthly_tracker_id"):
        return api_response(400, "user_monthly_tracker_id is required")

    umt_id = int(data["user_monthly_tracker_id"])

    query = f"""
        SELECT
            umt.user_monthly_tracker_id,
            umt.user_id,
            u.user_name,
            umt.month_year,
            umt.monthly_target,
            umt.created_date,
            umt.is_active,

            COALESCE(SUM(twt.production), 0) AS total_production,
            COALESCE(SUM(twt.billable_hours), 0) AS total_billable_hours,
            COUNT(twt.tracker_id) AS tracker_rows,

            {WORKING_DAYS_SQL}

        FROM user_monthly_tracker umt
        LEFT JOIN tfs_user u ON u.user_id = umt.user_id

        LEFT JOIN task_work_tracker twt
          ON twt.user_id = umt.user_id
         AND twt.is_active = 1
         AND {TRACKER_YEAR_MONTH} = {month_year_to_yyyymm_sql("umt.month_year")}

        WHERE umt.user_monthly_tracker_id=%s
          AND umt.is_active=1
        GROUP BY umt.user_monthly_tracker_id
    """

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(query, (umt_id,))
        row = cursor.fetchone()
        if not row:
            return api_response(404, "Record not found")
        return api_response(200, "User monthly target fetched successfully", row)

    except Exception as e:
        return api_response(500, f"View failed: {str(e)}")
    finally:
        cursor.close()
        conn.close()
