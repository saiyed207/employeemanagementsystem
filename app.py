import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MOCK_TOKEN = "mock-javagoat-token"

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY environment variables are required.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)

ALLOWED_FIELDS = {
    "departments": {"name", "description", "status"},
    "positions": {"title", "department_id", "level", "status"},
    "employees": {
        "first_name",
        "last_name",
        "email",
        "phone",
        "hire_date",
        "salary",
        "status",
        "department_id",
        "position_id",
        "profile_pic",
    },
    "attendance": {"employee_id", "date", "check_in", "check_out", "status"},
    "leaves": {"employee_id", "start_date", "end_date", "type", "status", "reason"},
    "payroll": {
        "employee_id",
        "pay_period",
        "basic_salary",
        "bonus",
        "deductions",
        "net_pay",
        "status",
    },
}

NUMERIC_FIELDS = {
    "salary",
    "basic_salary",
    "bonus",
    "deductions",
    "net_pay",
}

TABLES = tuple(ALLOWED_FIELDS.keys())


def api_error(message, status=400):
    return jsonify({"error": str(message)}), status


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {MOCK_TOKEN}":
            return api_error("Unauthorized", 401)
        return fn(*args, **kwargs)

    return wrapper


def clean_payload(table_name, payload):
    allowed = ALLOWED_FIELDS[table_name]
    cleaned = {}

    for key, value in (payload or {}).items():
        if key not in allowed:
            continue

        if value == "":
            value = None

        if key in NUMERIC_FIELDS and value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be numeric")

        cleaned[key] = value

    return cleaned


def supabase_data(query):
    result = query.execute()
    return result.data or []


def fetch_table(table_name):
    return supabase_data(
        supabase.table(table_name)
        .select("*")
        .order("created_at", desc=True)
    )


def parse_date(value):
    if not value:
        return None
    value = str(value)
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def month_key(dt):
    return dt.strftime("%b %Y")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "JavaGoat HR"})


@app.post("/api/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = payload.get("email")
    password = payload.get("password")

    if email == "admin@javagoat.hr" and password == "password123":
        return jsonify(
            {
                "token": MOCK_TOKEN,
                "user": {
                    "email": "admin@javagoat.hr",
                    "name": "JavaGoat Admin",
                    "role": "HR Operations",
                },
            }
        )

    return api_error("Invalid email or password", 401)


@app.get("/api/<table_name>")
@require_auth
def list_records(table_name):
    if table_name not in TABLES:
        return api_error("Unknown resource", 404)

    try:
        data = fetch_table(table_name)
        return jsonify({"data": data})
    except Exception as exc:
        return api_error(exc, 500)


@app.get("/api/<table_name>/<record_id>")
@require_auth
def get_record(table_name, record_id):
    if table_name not in TABLES:
        return api_error("Unknown resource", 404)

    try:
        data = supabase_data(
            supabase.table(table_name)
            .select("*")
            .eq("id", record_id)
            .limit(1)
        )
        if not data:
            return api_error("Record not found", 404)
        return jsonify({"data": data[0]})
    except Exception as exc:
        return api_error(exc, 500)


@app.post("/api/<table_name>")
@require_auth
def create_record(table_name):
    if table_name not in TABLES:
        return api_error("Unknown resource", 404)

    try:
        payload = clean_payload(table_name, request.get_json(silent=True) or {})
        if not payload:
            return api_error("No valid fields supplied", 400)

        data = supabase_data(
            supabase.table(table_name)
            .insert(payload)
        )
        return jsonify({"data": data[0] if data else None}), 201
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@app.put("/api/<table_name>/<record_id>")
@require_auth
def update_record(table_name, record_id):
    if table_name not in TABLES:
        return api_error("Unknown resource", 404)

    try:
        payload = clean_payload(table_name, request.get_json(silent=True) or {})

        if not payload:
            return api_error("No valid fields supplied", 400)

        data = supabase_data(
            supabase.table(table_name)
            .update(payload)
            .eq("id", record_id)
        )

        if not data:
            return api_error("Record not found", 404)

        return jsonify({"data": data[0]})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@app.delete("/api/<table_name>/<record_id>")
@require_auth
def delete_record(table_name, record_id):
    if table_name not in TABLES:
        return api_error("Unknown resource", 404)

    try:
        data = supabase_data(
            supabase.table(table_name)
            .delete()
            .eq("id", record_id)
        )
        return jsonify({"data": data})
    except Exception as exc:
        return api_error(exc, 500)


@app.get("/api/dashboard/stats")
@require_auth
def dashboard_stats():
    try:
        departments = fetch_table("departments")
        positions = fetch_table("positions")
        employees = fetch_table("employees")
        attendance = fetch_table("attendance")
        leaves = fetch_table("leaves")
        payroll = fetch_table("payroll")

        dept_map = {str(d["id"]): d for d in departments}
        pos_map = {str(p["id"]): p for p in positions}

        active_employees = [
            e for e in employees if str(e.get("status", "")).lower() == "active"
        ]

        latest_period = None
        for row in payroll:
            period = row.get("pay_period")
            if period and (latest_period is None or str(period) > str(latest_period)):
                latest_period = period

        if latest_period:
            payroll_total = sum(
                float(p.get("net_pay") or 0)
                for p in payroll
                if str(p.get("pay_period")) == str(latest_period)
            )
        else:
            payroll_total = sum(float(p.get("net_pay") or 0) for p in payroll)

        cards = {
            "total_employees": len(employees),
            "active_employees": len(active_employees),
            "departments": len(departments),
            "positions": len([p for p in positions if p.get("status") == "active"]),
            "payroll_total": payroll_total,
            "pending_leaves": len([l for l in leaves if l.get("status") == "pending"]),
        }

        now = datetime.utcnow()
        month_starts = []
        for i in range(5, -1, -1):
            y = now.year
            m = now.month - i
            while m <= 0:
                m += 12
                y -= 1
            month_starts.append(datetime(y, m, 1))

        hiring_counts = Counter()
        for employee in employees:
            dt = parse_date(employee.get("hire_date"))
            if dt:
                hiring_counts[(dt.year, dt.month)] += 1

        hiring_labels = [month_key(dt) for dt in month_starts]
        hiring_data = [hiring_counts[(dt.year, dt.month)] for dt in month_starts]

        department_counts = Counter()
        for employee in employees:
            dept = dept_map.get(str(employee.get("department_id")))
            department_counts[dept["name"] if dept else "Unassigned"] += 1

        if department_counts:
            dept_labels = list(department_counts.keys())
            dept_data = list(department_counts.values())
        else:
            dept_labels = ["No Employees"]
            dept_data = [1]

        position_employees = []
        for employee in sorted(employees, key=lambda e: (e.get("first_name") or "", e.get("last_name") or "")):
            position = pos_map.get(str(employee.get("position_id")))
            full_name = f"{employee.get('first_name') or ''} {employee.get('last_name') or ''}".strip()
            position_employees.append(
                {
                    "employee_id": employee.get("id"),
                    "employee_name": full_name or "Unnamed Employee",
                    "email": employee.get("email"),
                    "profile_pic": employee.get("profile_pic"),
                    "position_title": position.get("title") if position else "Unassigned",
                }
            )

        last_seven_dates = [
            (datetime.utcnow().date() - timedelta(days=i)).isoformat()
            for i in range(6, -1, -1)
        ]

        attendance_counts = Counter()
        for row in attendance:
            if row.get("status") == "present" and row.get("date"):
                attendance_counts[str(row.get("date"))[:10]] += 1

        attendance_trend = {
            "labels": [datetime.strptime(d, "%Y-%m-%d").strftime("%d %b") for d in last_seven_dates],
            "data": [attendance_counts[d] for d in last_seven_dates],
        }

        status_counts = Counter(
            human_status(employee.get("status") or "unknown")
            for employee in employees
        )

        if status_counts:
            status_labels = list(status_counts.keys())
            status_data = list(status_counts.values())
        else:
            status_labels = ["No Employees"]
            status_data = [1]

        return jsonify(
            {
                "cards": cards,
                "hiring_trend": {
                    "labels": hiring_labels,
                    "data": hiring_data,
                },
                "department_mix": {
                    "labels": dept_labels,
                    "data": dept_data,
                },
                "position_employees": position_employees,
                "attendance_trend": attendance_trend,
                "status_breakdown": {
                    "labels": status_labels,
                    "data": status_data,
                },
            }
        )
    except Exception as exc:
        return api_error(exc, 500)


def human_status(value):
    return str(value).replace("_", " ").title()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
