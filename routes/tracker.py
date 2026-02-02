from flask import Blueprint, request
from config import get_db_connection, BASE_UPLOAD_URL, UPLOAD_SUBDIRS
from utils.response import api_response
from utils.file_utils import save_base64_file
from utils.api_log_utils import log_api_call
from datetime import datetime

tracker_bp = Blueprint("tracker", __name__)

UPLOAD_URL_PREFIX = "/uploads"


# ------------------------
# HELPERS
# ------------------------

def calculate_targets(base_target, user_tenure):
    user_tenure = float(user_tenure)
    base_target = float(base_target)
    actual_target = base_target * 1
    tenure_target = round(base_target * user_tenure, 2)
    return actual_target, tenure_target


def normalize_month_year(month_year: str) -> str:
    """
    Accepts any case input like 'jan2026', 'JAN2026', 'Jan2026'
    Returns normalized 'Jan2026'.
    """
    month_year = (month_year or "").strip()
    if not month_year:
        return ""

    # Must at least have 3 letters + 4 digits (example: Jan2026)
    # But we won't hard-fail; we'll normalize best-effort.
    s = month_year.lower()
    month_abbr = s[:3].capitalize()          # jan -> Jan
    year_part = s[3:]                        # 2026
    return f"{month_abbr}{year_part}"


def get_role_context(cursor, user_id: int) -> dict:
    cursor.execute(
        """
        SELECT
            u.role_id AS user_role_id,
            r.role_name AS user_role_name,
            (
                SELECT ur2.role_id
                FROM user_role ur2
                WHERE LOWER(TRIM(ur2.role_name)) = 'agent'
                LIMIT 1
            ) AS agent_role_id
        FROM tfs_user u
        JOIN user_role r ON r.role_id = u.role_id
        WHERE u.user_id=%s AND u.is_active=1 AND u.is_delete=1
        """,
        (int(user_id),),
    )
    row = cursor.fetchone() or {}
    return {
        "user_role_id": row.get("user_role_id"),
        "user_role_name": (row.get("user_role_name") or "").strip().lower(),
        "agent_role_id": row.get("agent_role_id"),
    }


def cleaned_csv_col(col_sql: str) -> str:
    """
    Your DB sometimes stores ids like:
      "[111, 113]" or "[111]"
    This helper returns SQL that removes spaces and brackets, so FIND_IN_SET works.
    """
    return f"REPLACE(REPLACE(REPLACE({col_sql}, '[', ''), ']', ''), ' ', '')"


# ------------------------
# ADD TRACKER
# ------------------------
@tracker_bp.route("/add", methods=["POST"])
def add_tracker():
    data = request.get_json()
    required_fields = ["project_id", "task_id", "user_id", "production"]

    for field in required_fields:
        if field not in data:
            return api_response(400, f"{field} is required")

    project_id = data["project_id"]
    task_id = data["task_id"]
    user_id = data["user_id"]
    production = float(data["production"])
    tenure_target = float(data["tenure_target"])
    tracker_file_base64 = data.get("tracker_file")
    tracker_file = None
    is_active = 1
    billable_hours = production / tenure_target

    if tracker_file_base64:
        tracker_file = save_base64_file(tracker_file_base64, UPLOAD_SUBDIRS["TRACKER_FILES"])

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT task_target FROM task WHERE task_id=%s", (task_id,))
        user = cursor.fetchone()
        if not user:
            return api_response(404, "Task not found")

        actual_target = user["task_target"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            INSERT INTO task_work_tracker
            (project_id, task_id, user_id, production, actual_target, tenure_target, billable_hours,
             tracker_file, tracker_file_base64, is_active, date_time, updated_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                project_id,
                task_id,
                user_id,
                production,
                actual_target,
                tenure_target,
                billable_hours,
                tracker_file,
                tracker_file_base64,
                is_active,
                now,
                now,
            ),
        )

        conn.commit()
        tracker_id = cursor.lastrowid

        device_id = data.get("device_id")
        device_type = data.get("device_type")
        api_call_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_api_call("add_tracker", user_id, device_id, device_type, api_call_time)

        return api_response(201, "Tracker added successfully", {"tracker_id": tracker_id})

    except Exception as e:
        conn.rollback()
        return api_response(500, f"Failed to add tracker: {str(e)}")

    finally:
        cursor.close()
        conn.close()


# ------------------------
# UPDATE TRACKER
# ------------------------
@tracker_bp.route("/update", methods=["POST"])
def update_tracker():
    data = request.get_json()
    tracker_id = data.get("tracker_id")
    if not tracker_id:
        return api_response(400, "tracker_id is required")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM task_work_tracker WHERE tracker_id=%s", (tracker_id,))
        tracker = cursor.fetchone()
        if not tracker:
            return api_response(404, "Tracker not found")

        new_user_id = tracker["user_id"]

        cursor.execute("SELECT user_tenure FROM tfs_user WHERE user_id=%s", (new_user_id,))
        user = cursor.fetchone()
        if not user:
            return api_response(404, "User not found")

        production = float(data.get("production", tracker["production"]))
        base_target = float(data.get("base_target", tracker["actual_target"]))

        tracker_file_base64 = data.get("tracker_file_base64")
        tracker_file = tracker["tracker_file"]
        if tracker_file_base64:
            tracker_file = save_base64_file(tracker_file_base64, UPLOAD_SUBDIRS["TRACKER_FILES"])

        actual_target, tenure_target = calculate_targets(base_target, user["user_tenure"])
        updated_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            UPDATE task_work_tracker
            SET user_id=%s, production=%s, actual_target=%s, tenure_target=%s,
                tracker_file=%s, tracker_file_base64=%s, updated_date=%s
            WHERE tracker_id=%s
            """,
            (
                new_user_id,
                production,
                actual_target,
                tenure_target,
                tracker_file,
                tracker_file_base64,
                updated_date,
                tracker_id,
            ),
        )

        conn.commit()

        device_id = data.get("device_id")
        device_type = data.get("device_type")
        api_call_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_api_call("update_tracker", tracker["user_id"], device_id, device_type, api_call_time)

        return api_response(200, "Tracker updated successfully")

    except Exception as e:
        conn.rollback()
        return api_response(500, f"Failed to update tracker: {str(e)}")

    finally:
        cursor.close()
        conn.close()


# ------------------------
# VIEW TRACKERS (your existing logic + month_year normalization + robust manager matching)
# ------------------------
@tracker_bp.route("/view", methods=["POST"])
def view_trackers():
    data = request.get_json() or {}

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        params = []

        logged_in_user_id = data.get("logged_in_user_id")
        if not logged_in_user_id:
            return api_response(400, "logged_in_user_id is required")

        # month_year default current month
        month_year = normalize_month_year(data.get("month_year"))
        if not month_year:
            cursor.execute("SELECT DATE_FORMAT(CURDATE(), '%b%Y') AS m")
            month_year = normalize_month_year((cursor.fetchone() or {}).get("m") or "")

        ctx = get_role_context(cursor, int(logged_in_user_id))
        role_name = ctx["user_role_name"]

        query = """
            SELECT 
                twt.*,
                u.user_name,
                p.project_name,
                tk.task_name,
                t.team_name,
                (twt.production / NULLIF(twt.tenure_target, 0)) AS billable_hours
            FROM task_work_tracker twt
            LEFT JOIN tfs_user u ON u.user_id = twt.user_id
            LEFT JOIN project p ON p.project_id = twt.project_id
            LEFT JOIN task tk ON tk.task_id = twt.task_id
            LEFT JOIN team t ON u.team_id = t.team_id
            WHERE twt.is_active != 0
        """

        # month filter
        try:
            dt = datetime.strptime(month_year, "%b%Y")
            query += " AND YEAR(CAST(twt.date_time AS DATETIME)) = %s AND MONTH(CAST(twt.date_time AS DATETIME)) = %s"
            params.extend([dt.year, dt.month])
        except Exception:
            pass

        if data.get("team_id"):
            query += " AND u.team_id=%s"
            params.append(data["team_id"])

        if data.get("user_id"):
            query += " AND twt.user_id=%s"
            params.append(data["user_id"])
        else:
            if role_name in ("admin", "super admin"):
                pass
            else:
                manager_id_str = str(logged_in_user_id)
                query += f"""
                    AND twt.user_id IN (
                        SELECT tu.user_id
                        FROM tfs_user tu
                        WHERE tu.is_active = 1
                          AND tu.is_delete = 1
                          AND (
                                tu.project_manager_id = %s
                                OR tu.asst_manager_id = %s
                                OR tu.qa_id = %s
                                OR tu.user_id = %s
                                OR FIND_IN_SET(%s, {cleaned_csv_col("tu.project_manager_id")}) > 0
                                OR FIND_IN_SET(%s, {cleaned_csv_col("tu.asst_manager_id")}) > 0
                                OR FIND_IN_SET(%s, {cleaned_csv_col("tu.qa_id")}) > 0
                          )
                    )
                """
                params.extend([manager_id_str] * 7)

        if data.get("project_id"):
            query += " AND twt.project_id=%s"
            params.append(data["project_id"])

        if data.get("task_id"):
            query += " AND twt.task_id=%s"
            params.append(data["task_id"])

        if data.get("date_from"):
            date_from = data["date_from"]
            if len(date_from) == 10:
                date_from += " 00:00:00"
            query += " AND CAST(twt.date_time AS DATETIME) >= %s"
            params.append(date_from)

        if data.get("date_to"):
            date_to = data["date_to"]
            if len(date_to) == 10:
                date_to += " 23:59:59"
            query += " AND CAST(twt.date_time AS DATETIME) <= %s"
            params.append(date_to)

        if data.get("is_active") is not None:
            query += " AND twt.is_active=%s"
            params.append(data["is_active"])

        query += " ORDER BY CAST(twt.date_time AS DATETIME) DESC"

        cursor.execute(query, tuple(params))
        trackers = cursor.fetchall()

        tracker_files_url = f"{BASE_UPLOAD_URL}/{UPLOAD_SUBDIRS['TRACKER_FILES']}/"
        for t in trackers:
            tracker_file_temp = t.get("tracker_file")
            t["tracker_file"] = (tracker_files_url + tracker_file_temp) if tracker_file_temp else None

        # Month-wise summary (your logic, but month_year is normalized now)
        user_ids = sorted({t.get("user_id") for t in trackers if t.get("user_id") is not None})
        month_summary = []

        if user_ids:
            in_ph = ",".join(["%s"] * len(user_ids))

            summary_query = f"""
                SELECT
                    u.user_id,
                    u.user_name,
                    m.mon AS month_year,
                    umt.user_monthly_tracker_id,
                    COALESCE(CAST(umt.monthly_target AS DECIMAL(10,2)), 0) AS monthly_target,
                    COALESCE(umt.extra_assigned_hours, 0) AS extra_assigned_hours,
                    (
                      COALESCE(CAST(umt.monthly_target AS DECIMAL(10,2)), 0)
                      + COALESCE(umt.extra_assigned_hours, 0)
                    ) AS monthly_total_target,
                    COALESCE((
                      SELECT SUM(twt3.production / NULLIF(twt3.tenure_target, 0))
                      FROM task_work_tracker twt3
                      WHERE twt3.user_id = u.user_id
                        AND twt3.is_active = 1
                        AND (YEAR(CAST(twt3.date_time AS DATETIME))*100 + MONTH(CAST(twt3.date_time AS DATETIME))) = m.yyyymm
                    ), 0) AS total_billable_hours_month,
                    CASE
                      WHEN umt.user_monthly_tracker_id IS NULL THEN NULL
                      ELSE GREATEST(
                             COALESCE(CAST(umt.working_days AS SIGNED), 0)
                             - COALESCE((
                                 SELECT COUNT(DISTINCT DATE(CAST(twt2.date_time AS DATETIME)))
                                 FROM task_work_tracker twt2
                                 WHERE twt2.user_id = u.user_id
                                   AND twt2.is_active = 1
                                   AND (YEAR(CAST(twt2.date_time AS DATETIME))*100 + MONTH(CAST(twt2.date_time AS DATETIME))) = m.yyyymm
                                   AND DATE(CAST(twt2.date_time AS DATETIME)) <= m.cutoff
                               ), 0),
                             0
                           )
                    END AS pending_days,
                    CASE
                      WHEN umt.user_monthly_tracker_id IS NULL THEN NULL
                      WHEN GREATEST(
                             COALESCE(CAST(umt.working_days AS SIGNED), 0)
                             - COALESCE((
                                 SELECT COUNT(DISTINCT DATE(CAST(twt2.date_time AS DATETIME)))
                                 FROM task_work_tracker twt2
                                 WHERE twt2.user_id = u.user_id
                                   AND twt2.is_active = 1
                                   AND (YEAR(CAST(twt2.date_time AS DATETIME))*100 + MONTH(CAST(twt2.date_time AS DATETIME))) = m.yyyymm
                                   AND DATE(CAST(twt2.date_time AS DATETIME)) <= m.cutoff
                               ), 0),
                             0
                           ) = 0 THEN NULL
                      ELSE
                        (
                          (
                            COALESCE(CAST(umt.monthly_target AS DECIMAL(10,2)), 0)
                            + COALESCE(umt.extra_assigned_hours, 0)
                          )
                          - COALESCE((
                              SELECT SUM(twt3.production / NULLIF(twt3.tenure_target, 0))
                              FROM task_work_tracker twt3
                              WHERE twt3.user_id = u.user_id
                                AND twt3.is_active = 1
                                AND (YEAR(CAST(twt3.date_time AS DATETIME))*100 + MONTH(CAST(twt3.date_time AS DATETIME))) = m.yyyymm
                            ), 0)
                        )
                        / NULLIF(
                            GREATEST(
                              COALESCE(CAST(umt.working_days AS SIGNED), 0)
                              - COALESCE((
                                  SELECT COUNT(DISTINCT DATE(CAST(twt2.date_time AS DATETIME)))
                                  FROM task_work_tracker twt2
                                  WHERE twt2.user_id = u.user_id
                                    AND twt2.is_active = 1
                                    AND (YEAR(CAST(twt2.date_time AS DATETIME))*100 + MONTH(CAST(twt2.date_time AS DATETIME))) = m.yyyymm
                                    AND DATE(CAST(twt2.date_time AS DATETIME)) <= m.cutoff
                                ), 0),
                              0
                            ),
                            0
                          )
                    END AS daily_required_hours
                FROM tfs_user u
                CROSS JOIN (
                    SELECT
                      %s AS mon,
                      CAST(DATE_FORMAT(STR_TO_DATE(CONCAT('01-', %s), '%d-%b%Y'), '%Y%m') AS UNSIGNED) AS yyyymm,
                      CASE
                        WHEN (YEAR(CURDATE())*100 + MONTH(CURDATE())) =
                             CAST(DATE_FORMAT(STR_TO_DATE(CONCAT('01-', %s), '%d-%b%Y'), '%Y%m') AS UNSIGNED)
                        THEN CURDATE()
                        WHEN (YEAR(CURDATE())*100 + MONTH(CURDATE())) >
                             CAST(DATE_FORMAT(STR_TO_DATE(CONCAT('01-', %s), '%d-%b%Y'), '%Y%m') AS UNSIGNED)
                        THEN LAST_DAY(STR_TO_DATE(CONCAT('01-', %s), '%d-%b%Y'))
                        ELSE DATE_SUB(STR_TO_DATE(CONCAT('01-', %s), '%d-%b%Y'), INTERVAL 1 DAY)
                      END AS cutoff
                ) m
                LEFT JOIN user_monthly_tracker umt
                  ON umt.user_id = u.user_id
                 AND umt.is_active = 1
                 AND umt.month_year = m.mon
                WHERE u.user_id IN ({in_ph})
            """

            summary_params = [month_year] * 6 + user_ids
            cursor.execute(summary_query, tuple(summary_params))
            month_summary = cursor.fetchall()

            device_id = data.get("device_id")
            device_type = data.get("device_type")
            api_call_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_api_call("view_trackers", logged_in_user_id, device_id, device_type, api_call_time)

        return api_response(
            200,
            "Trackers fetched successfully",
            {
                "count": len(trackers),
                "month_year": month_year,
                "trackers": trackers,
                "month_summary": month_summary,
            },
        )

    except Exception as e:
        return api_response(500, f"Failed to fetch trackers: {str(e)}")

    finally:
        cursor.close()
        conn.close()


@tracker_bp.route("/view_daily", methods=["POST"])
def view_daily_trackers():
    data = request.get_json() or {}

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        params = []

        logged_in_user_id = data.get("logged_in_user_id")
        if not logged_in_user_id:
            return api_response(400, "logged_in_user_id is required")

        # -------- Month (case-insensitive, same behavior as view)
        month_year = normalize_month_year(data.get("month_year"))
        if not month_year:
            cursor.execute("SELECT DATE_FORMAT(CURDATE(), '%b%Y') AS m")
            month_year = normalize_month_year((cursor.fetchone() or {}).get("m") or "")

        # -------- Role check (DO NOT depend on is_delete)
        cursor.execute(
            """
            SELECT LOWER(TRIM(r.role_name)) AS role_name
            FROM tfs_user u
            JOIN user_role r ON r.role_id = u.role_id
            WHERE u.user_id=%s
            LIMIT 1
            """,
            (int(logged_in_user_id),),
        )
        role_name = ((cursor.fetchone() or {}).get("role_name") or "").lower()

        where = "WHERE twt.is_active != 0"

        # -------- Month filter
        try:
            dt = datetime.strptime(month_year, "%b%Y")
            where += " AND YEAR(CAST(twt.date_time AS DATETIME))=%s AND MONTH(CAST(twt.date_time AS DATETIME))=%s"
            params.extend([dt.year, dt.month])
        except Exception:
            pass

        # -------- Same filters as /view
        if data.get("team_id"):
            where += " AND u.team_id=%s"
            params.append(data["team_id"])

        if data.get("project_id"):
            where += " AND twt.project_id=%s"
            params.append(data["project_id"])

        if data.get("task_id"):
            where += " AND twt.task_id=%s"
            params.append(data["task_id"])

        if data.get("date_from"):
            date_from = data["date_from"]
            if len(date_from) == 10:
                date_from += " 00:00:00"
            where += " AND CAST(twt.date_time AS DATETIME) >= %s"
            params.append(date_from)

        if data.get("date_to"):
            date_to = data["date_to"]
            if len(date_to) == 10:
                date_to += " 23:59:59"
            where += " AND CAST(twt.date_time AS DATETIME) <= %s"
            params.append(date_to)

        if data.get("is_active") is not None:
            where += " AND twt.is_active=%s"
            params.append(data["is_active"])

        # -------- User filter OR restriction (same logic as view)
        if data.get("user_id"):
            where += " AND twt.user_id=%s"
            params.append(data["user_id"])
        else:
            if "admin" not in role_name:
                manager_id = str(logged_in_user_id)
                where += f"""
                    AND twt.user_id IN (
                        SELECT tu.user_id
                        FROM tfs_user tu
                        WHERE tu.is_active = 1
                          AND tu.is_delete = 1
                          AND (
                                tu.project_manager_id = %s
                                OR tu.asst_manager_id = %s
                                OR tu.qa_id = %s
                                OR tu.user_id = %s
                                OR FIND_IN_SET(%s, {cleaned_csv_col("tu.project_manager_id")}) > 0
                                OR FIND_IN_SET(%s, {cleaned_csv_col("tu.asst_manager_id")}) > 0
                                OR FIND_IN_SET(%s, {cleaned_csv_col("tu.qa_id")}) > 0
                          )
                    )
                """
                params.extend([manager_id] * 7)

        # -------- Daily aggregation + cumulative + daily required
        query = f"""
            WITH daily AS (
                SELECT
                    twt.user_id,
                    DATE(CAST(twt.date_time AS DATETIME)) AS work_date,
                    SUM(COALESCE(twt.production, 0)) AS total_production_day,
                    SUM(COALESCE(twt.production, 0) / NULLIF(twt.tenure_target, 0)) AS total_billable_hours_day,
                    COUNT(*) AS trackers_count_day
                FROM task_work_tracker twt
                LEFT JOIN tfs_user u ON u.user_id = twt.user_id
                {where}
                GROUP BY twt.user_id, DATE(CAST(twt.date_time AS DATETIME))
            ),
            daily_with_cum AS (
                SELECT
                    d.*,
                    SUM(d.total_billable_hours_day)
                        OVER (PARTITION BY d.user_id ORDER BY d.work_date)
                        AS cumulative_billable_hours_till_day,
                    COUNT(*) OVER (PARTITION BY d.user_id ORDER BY d.work_date)
                        AS worked_days_till_day
                FROM daily d
            )
            SELECT
                dwc.user_id,
                u.user_name,
                dwc.work_date,

                dwc.total_production_day,
                ROUND(dwc.total_billable_hours_day, 4) AS total_billable_hours_day,
                dwc.trackers_count_day,

                ROUND(dwc.cumulative_billable_hours_till_day, 4)
                    AS cumulative_billable_hours_till_day,

                umt.user_monthly_tracker_id,
                COALESCE(CAST(umt.monthly_target AS DECIMAL(10,2)), 0) AS monthly_target,
                COALESCE(umt.extra_assigned_hours, 0) AS extra_assigned_hours,
                (
                  COALESCE(CAST(umt.monthly_target AS DECIMAL(10,2)), 0)
                  + COALESCE(umt.extra_assigned_hours, 0)
                ) AS monthly_total_target,

                CAST(umt.working_days AS SIGNED) AS working_days,

                GREATEST(
                    COALESCE(CAST(umt.working_days AS SIGNED), 0)
                    - COALESCE(dwc.worked_days_till_day, 0),
                    0
                ) AS pending_days_after_this_day,

                CASE
                  WHEN umt.user_monthly_tracker_id IS NULL THEN NULL
                  WHEN GREATEST(
                        COALESCE(CAST(umt.working_days AS SIGNED), 0)
                        - COALESCE(dwc.worked_days_till_day, 0),
                        0
                      ) = 0 THEN NULL
                  ELSE
                    (
                      (
                        COALESCE(CAST(umt.monthly_target AS DECIMAL(10,2)), 0)
                        + COALESCE(umt.extra_assigned_hours, 0)
                      )
                      - COALESCE(dwc.cumulative_billable_hours_till_day, 0)
                    )
                    / NULLIF(
                        GREATEST(
                            COALESCE(CAST(umt.working_days AS SIGNED), 0)
                            - COALESCE(dwc.worked_days_till_day, 0),
                            0
                        ),
                        0
                      )
                END AS daily_required_hours
            FROM daily_with_cum dwc
            JOIN tfs_user u ON u.user_id = dwc.user_id
            LEFT JOIN user_monthly_tracker umt
              ON umt.user_id = dwc.user_id
             AND umt.is_active = 1
             AND umt.month_year = %s
            ORDER BY dwc.work_date DESC, u.user_name ASC
        """

        final_params = list(params) + [month_year]
        cursor.execute(query, tuple(final_params))
        rows = cursor.fetchall()

        # -------- Response KEYS SAME AS /view
        return api_response(
            200,
            "Trackers fetched successfully",
            {
                "count": len(rows),
                "month_year": month_year,
                "trackers": rows,      # 🔑 SAME KEY AS VIEW
                "month_summary": []    # 🔑 KEPT FOR FRONTEND COMPATIBILITY
            },
        )

    except Exception as e:
        return api_response(500, f"Failed to fetch daily trackers: {str(e)}")

    finally:
        cursor.close()
        conn.close()



# ------------------------
# DELETE TRACKER (SOFT DELETE)
# ------------------------
@tracker_bp.route("/delete", methods=["POST"])
def delete_tracker():
    data = request.get_json() or {}

    tracker_id = data.get("tracker_id")
    if not tracker_id:
        return api_response(400, "tracker_id is required")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT tracker_id, user_id FROM task_work_tracker WHERE tracker_id=%s",
            (tracker_id,),
        )
        tracker = cursor.fetchone()

        if not tracker:
            return api_response(404, "Tracker not found")

        cursor.execute(
            """
            UPDATE task_work_tracker
            SET is_active = 0
            WHERE tracker_id = %s
            """,
            (tracker_id,),
        )

        conn.commit()

        device_id = data.get("device_id")
        device_type = data.get("device_type")
        api_call_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_api_call("delete_tracker", tracker["user_id"], device_id, device_type, api_call_time)

        return api_response(200, "Tracker deleted successfully")

    except Exception as e:
        conn.rollback()
        return api_response(500, f"Failed to delete tracker: {str(e)}")

    finally:
        cursor.close()
        conn.close()
