"""BugFlow local application server: Python standard library + SQLite only."""
from __future__ import annotations

import base64
import calendar
from contextlib import contextmanager
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("BUGFLOW_DB", str(ROOT / "bugflow.sqlite3")))
MAX_BODY = 10 * 1024 * 1024
FLOW = {"Open": {"In Progress"}, "In Progress": {"Testing"}, "Testing": {"Resolved", "In Progress"}, "Resolved": {"Closed", "In Progress"}, "Closed": set()}
WORK_ITEM_KINDS = {"Issue", "Epic", "Story", "Task"}
DEMO_USERS = [
    ("gaurav", "admin123", "U1", "Admin"),
    ("maya", "manager123", "U2", "Project Manager"),
    ("arjun", "dev123", "U3", "Developer"),
    ("neha", "tester123", "U4", "Tester"),
]


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def password_hash(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or secrets.token_bytes(16)
    return salt, hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)


def initialize():
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK(id=1), json TEXT NOT NULL, updated_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS accounts (username TEXT PRIMARY KEY, salt BLOB NOT NULL, password_hash BLOB NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS attachments (id TEXT PRIMARY KEY, issue_id TEXT NOT NULL, filename TEXT NOT NULL, content_type TEXT NOT NULL, size INTEGER NOT NULL, data BLOB NOT NULL, created_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        if not db.execute("SELECT 1 FROM settings WHERE key='token_secret'").fetchone():
            db.execute("INSERT INTO settings(key,value) VALUES('token_secret',?)", (secrets.token_urlsafe(48),))
        for username, password, user_id, role in DEMO_USERS:
            if not db.execute("SELECT 1 FROM accounts WHERE username=?", (username,)).fetchone():
                salt, digest = password_hash(password)
                db.execute("INSERT INTO accounts VALUES(?,?,?,?,?)", (username, salt, digest, user_id, role))


def sign_token(account: sqlite3.Row) -> str:
    with connect() as db:
        secret = db.execute("SELECT value FROM settings WHERE key='token_secret'").fetchone()["value"].encode()
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip("=")
    payload = {"sub": account["username"], "uid": account["user_id"], "role": account["role"], "exp": int(time.time()) + 8 * 60 * 60}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(hmac.new(secret, (header + "." + body).encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return header + "." + body + "." + signature


def verify_token(token: str) -> dict | None:
    try:
        header, body, signature = token.split(".")
        with connect() as db:
            secret = db.execute("SELECT value FROM settings WHERE key='token_secret'").fetchone()["value"].encode()
        expected = base64.urlsafe_b64encode(hmac.new(secret, (header + "." + body).encode(), hashlib.sha256).digest()).decode().rstrip("=")
        if not hmac.compare_digest(signature, expected):
            return None
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if claims.get("exp", 0) < time.time():
            return None
        return claims
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def stored_state():
    with connect() as db:
        row = db.execute("SELECT json FROM app_state WHERE id=1").fetchone()
        return json.loads(row["json"]) if row else None


def write_state(state: dict):
    with connect() as db:
        db.execute("INSERT INTO app_state(id,json,updated_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET json=excluded.json,updated_at=excluded.updated_at", (json.dumps(state, ensure_ascii=False), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))


def record_activity(state: dict, claims: dict, issue: dict, message: str):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    event = {"id": secrets.token_hex(5), "userId": claims["uid"], "text": message, "issueId": issue["id"], "createdAt": stamp}
    issue.setdefault("history", []).insert(0, event)
    issue["updatedAt"] = stamp
    state.setdefault("activity", []).insert(0, event)
    state["activity"] = state["activity"][:100]


def validate_state(old: dict | None, new: dict, claims: dict) -> str | None:
    if not isinstance(new, dict) or not isinstance(new.get("issues"), list) or not isinstance(new.get("users"), list):
        return "State payload must include users and issues arrays."
    role = claims["role"]
    old = old or {"issues": [], "users": [], "sprints": [], "releases": []}
    def indexed(state, key):
        return {item.get("id"): item for item in state.get(key, []) if isinstance(item, dict) and item.get("id")}
    old_issues, new_issues = indexed(old, "issues"), indexed(new, "issues")
    if len(new_issues) != len(new.get("issues", [])):
        return "Every issue must have a unique id."
    if old.get("users") and role not in ("Admin", "Project Manager") and (old.get("users") != new.get("users") or old.get("sprints") != new.get("sprints") or old.get("releases") != new.get("releases")):
        return "Only admins and project managers can manage team, sprint, and release data."
    for issue_id, item in new_issues.items():
        if item.get("status") not in FLOW:
            return "Unknown issue status."
        kind = item.get("workItemKind", "Issue")
        if kind not in WORK_ITEM_KINDS:
            return "Unknown work item kind."
        parent_id = item.get("parentId")
        if parent_id:
            parent = new_issues.get(parent_id)
            if parent_id == issue_id or not parent or parent.get("workItemKind", "Issue") not in {"Epic", "Story", "Task"}:
                return "Parent must reference a different epic, story, or task in this workspace."
            seen = {issue_id}
            while parent_id:
                if parent_id in seen:
                    return "Work item relationships cannot contain a cycle."
                seen.add(parent_id)
                ancestor = new_issues.get(parent_id)
                parent_id = ancestor.get("parentId") if ancestor else None
        reference = item.get("referenceUrl")
        if reference:
            parsed = urlparse(reference)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return "Code references must use an http or https URL."
        previous = old_issues.get(issue_id)
        if previous and previous.get("status") != item.get("status") and item["status"] not in FLOW.get(previous.get("status"), set()):
            return "Invalid status transition: " + str(previous.get("status")) + " → " + item["status"] + "."
        if not previous and role not in ("Admin", "Project Manager") and (item.get("assigneeId") or item.get("sprintId")):
            return "Only admins and project managers can create assigned issues."
        if previous and role not in ("Admin", "Project Manager"):
            for field in ("assigneeId", "sprintId"):
                if previous.get(field) != item.get(field):
                    return "Only admins and project managers can change issue assignments."
    if any(not item.get("id") for item in new.get("sprints", [])):
        return "Every sprint must have an id."
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "BugFlow/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MAX_BODY:
            raise ValueError("Request body is too large.")
        return self.rfile.read(length)

    def read_json(self):
        try:
            return json.loads(self.read_body() or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid JSON request.") from exc

    def claims(self):
        auth = self.headers.get("Authorization", "")
        return verify_token(auth[7:]) if auth.startswith("Bearer ") else None

    def require_user(self):
        claims = self.claims()
        if not claims:
            self.send_json(401, {"error": "Sign in to continue."})
        return claims

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json(200, {"ok": True, "service": "BugFlow", "storage": "SQLite"})
            return
        if path == "/api/state":
            claims = self.require_user()
            if claims:
                self.send_json(200, {"state": stored_state(), "user": {"id": claims["uid"], "username": claims["sub"], "role": claims["role"]}})
            return
        if path == "/api/issues":
            if not self.require_user(): return
            state = stored_state() or {"issues": []}
            query = urlparse(self.path).query
            from urllib.parse import parse_qs
            args = parse_qs(query)
            issues = state.get("issues", [])
            for key in ("status", "type", "severity", "priority", "module"):
                value = args.get(key, [""])[0]
                if value: issues = [item for item in issues if item.get(key) == value]
            term = args.get("q", [""])[0].lower()
            if term: issues = [item for item in issues if term in " ".join(str(item.get(k, "")) for k in ("id", "title", "description", "module")).lower()]
            self.send_json(200, {"issues": issues, "count": len(issues)}); return
        if path == "/api/sprints":
            if not self.require_user(): return
            state = stored_state() or {}
            self.send_json(200, {"sprints": state.get("sprints", [])}); return
        if path == "/api/analytics/summary":
            if not self.require_user(): return
            issues = (stored_state() or {}).get("issues", [])
            self.send_json(200, {"total": len(issues), "byStatus": {s: sum(i.get("status") == s for i in issues) for s in FLOW}, "bySeverity": {s: sum(i.get("severity") == s for i in issues) for s in ("Critical", "High", "Medium", "Low")}}); return
        if path in ("/api/analytics/quality", "/api/reports/project"):
            if not self.require_user(): return
            from urllib.parse import parse_qs
            state = stored_state() or {}
            issues = state.get("issues", [])
            module = parse_qs(urlparse(self.path).query).get("module", [""])[0]
            if module:
                issues = [i for i in issues if i.get("module") == module]
            resolved = [i for i in issues if i.get("status") in ("Resolved", "Closed")]
            durations = []
            for issue in resolved:
                resolved_at = issue.get("resolutionAt")
                if not resolved_at:
                    events = [e.get("createdAt") for e in issue.get("history", []) if " to Resolved" in e.get("text", "") or " to Closed" in e.get("text", "")]
                    resolved_at = min(events) if events else None
                if issue.get("createdAt") and resolved_at:
                    try:
                        durations.append(max(0, (calendar.timegm(time.strptime(resolved_at[:19], "%Y-%m-%dT%H:%M:%S")) - calendar.timegm(time.strptime(issue["createdAt"][:19], "%Y-%m-%dT%H:%M:%S"))) / 3600))
                    except ValueError:
                        continue
            self.send_json(200, {"project": "BugFlow", "module": module or None, "total": len(issues), "byStatus": {s: sum(i.get("status") == s for i in issues) for s in FLOW}, "bySeverity": {s: sum(i.get("severity") == s for i in issues) for s in ("Critical", "High", "Medium", "Low")}, "byModule": {m: sum(i.get("module") == m for i in issues) for m in sorted({i.get("module", "Other") for i in issues})}, "resolved": len(resolved), "pending": len(issues) - len(resolved), "averageResolutionHours": round(sum(durations) / len(durations), 2) if durations else None}); return
        issue_match = re.fullmatch(r"/api/issues/([^/]+)", path)
        if issue_match:
            if not self.require_user(): return
            item = next((i for i in (stored_state() or {}).get("issues", []) if i.get("id") == unquote(issue_match.group(1))), None)
            if not item: self.send_json(404, {"error": "Issue not found."})
            else: self.send_json(200, {"issue": item})
            return
        match = re.fullmatch(r"/api/issues/([^/]+)/attachments(?:/([^/]+))?", path)
        if match:
            if not self.require_user(): return
            issue_id, file_id = map(lambda x: unquote(x) if x else None, match.groups())
            with connect() as db:
                if file_id:
                    row = db.execute("SELECT filename,content_type,size,data FROM attachments WHERE id=? AND issue_id=?", (file_id, issue_id)).fetchone()
                    if not row:
                        self.send_json(404, {"error": "Attachment not found."}); return
                    self.send_response(200)
                    self.send_header("Content-Type", row["content_type"])
                    self.send_header("Content-Length", str(row["size"]))
                    self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + __import__("urllib.parse", fromlist=["quote"]).quote(row["filename"]))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers(); self.wfile.write(row["data"]); return
                files = db.execute("SELECT id,filename,size,created_at FROM attachments WHERE issue_id=? ORDER BY created_at", (issue_id,)).fetchall()
            self.send_json(200, {"attachments": [dict(row) for row in files]}); return
        if path.startswith("/api/"):
            self.send_json(404, {"error": "API route not found."}); return
        self.serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/login":
            try: data = self.read_json()
            except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
            with connect() as db:
                account = db.execute("SELECT * FROM accounts WHERE username=?", (str(data.get("username", "")).strip().lower(),)).fetchone()
            if not account or not hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", str(data.get("password", "")).encode(), account["salt"], 240_000), account["password_hash"]):
                self.send_json(401, {"error": "Incorrect username or password."}); return
            self.send_json(200, {"token": sign_token(account), "user": {"id": account["user_id"], "username": account["username"], "role": account["role"]}}); return
        if path == "/api/integrations/github/status":
            secret = os.environ.get("BUGFLOW_WEBHOOK_SECRET", "")
            if not secret:
                self.send_json(503, {"error": "GitHub status sync is not configured."}); return
            try: raw = self.read_body()
            except ValueError as exc: self.send_json(413, {"error": str(exc)}); return
            supplied = self.headers.get("X-Hub-Signature-256", "")
            expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(supplied, expected):
                self.send_json(401, {"error": "Invalid GitHub webhook signature."}); return
            try: data = json.loads(raw or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_json(400, {"error": "Invalid JSON request."}); return
            if not isinstance(data, dict):
                self.send_json(422, {"error": "Webhook payload must be a JSON object."}); return
            conclusion = data.get("conclusion")
            issue_ids = data.get("issueIds", [])
            if conclusion not in ("success", "failure") or not isinstance(issue_ids, list):
                self.send_json(422, {"error": "A success or failure conclusion and issueIds array are required."}); return
            state = stored_state() or {}
            updated = []
            for item in state.get("issues", []):
                if item.get("id") not in issue_ids: continue
                previous = item.get("status")
                item["ciStatus"] = conclusion
                item["ciUpdatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if conclusion == "success" and previous == "In Progress": item["status"] = "Testing"
                elif conclusion == "failure" and previous == "Testing": item["status"] = "In Progress"
                event = {"id": secrets.token_hex(5), "userId": "github-actions", "text": "GitHub Actions " + conclusion + ("; moved issue from " + previous + " to " + item["status"] if previous != item["status"] else ""), "issueId": item["id"], "createdAt": item["ciUpdatedAt"]}
                item.setdefault("history", []).insert(0, event); item["updatedAt"] = event["createdAt"]
                state.setdefault("activity", []).insert(0, event); updated.append(item["id"])
            state["activity"] = state.get("activity", [])[:100]
            write_state(state)
            self.send_json(200, {"updated": updated, "conclusion": conclusion}); return
        if path == "/api/issues":
            claims = self.require_user()
            if not claims: return
            try: data = self.read_json()
            except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
            title = str(data.get("title", "")).strip()
            description = str(data.get("description", "")).strip()
            if not title or not description:
                self.send_json(422, {"error": "Issue title and description are required."}); return
            state = stored_state() or {"users": [], "issues": [], "sprints": [], "releases": [], "activity": []}
            if claims["role"] not in ("Admin", "Project Manager") and (data.get("assigneeId") or data.get("sprintId")):
                self.send_json(403, {"error": "Only admins and project managers can create assigned issues."}); return
            number = max([1040] + [int(re.search(r"\d+", i.get("id", "0")).group()) for i in state["issues"] if re.search(r"\d+", i.get("id", ""))]) + 1
            item = {"id": "BF-" + str(number), "title": title, "description": description, "type": data.get("type", "Bug"), "severity": data.get("severity", "Medium"), "priority": data.get("priority", "P2"), "module": data.get("module", "Other"), "workItemKind": data.get("workItemKind", "Issue"), "parentId": data.get("parentId", ""), "referenceUrl": data.get("referenceUrl", ""), "businessImpact": data.get("businessImpact", ""), "assigneeId": data.get("assigneeId"), "sprintId": data.get("sprintId"), "status": "Open", "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "comments": [], "history": []}
            state["issues"].insert(0, item); record_activity(state, claims, item, "created this " + str(item["type"]).lower()); write_state(state)
            self.send_json(201, {"issue": item}); return
        comment_match = re.fullmatch(r"/api/issues/([^/]+)/comments", path)
        if comment_match:
            claims = self.require_user()
            if not claims: return
            try: data = self.read_json()
            except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
            state = stored_state() or {}; item = next((i for i in state.get("issues", []) if i.get("id") == unquote(comment_match.group(1))), None)
            body = str(data.get("body", "")).strip()
            if not item: self.send_json(404, {"error": "Issue not found."}); return
            if not body: self.send_json(422, {"error": "Comment cannot be empty."}); return
            comment = {"id": secrets.token_hex(6), "authorId": claims["uid"], "body": body, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            item.setdefault("comments", []).append(comment); record_activity(state, claims, item, "added a comment"); write_state(state)
            self.send_json(201, {"comment": comment}); return
        if path == "/api/sprints":
            claims = self.require_user()
            if not claims: return
            if claims["role"] not in ("Admin", "Project Manager"):
                self.send_json(403, {"error": "Only admins and project managers can create sprints."}); return
            try: data = self.read_json()
            except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
            if not data.get("name") or not data.get("startDate") or not data.get("endDate") or data["endDate"] < data["startDate"]:
                self.send_json(422, {"error": "Sprint name and valid start/end dates are required."}); return
            state = stored_state() or {"users": [], "issues": [], "sprints": [], "releases": [], "activity": []}
            sprint = {"id": "SP-" + secrets.token_hex(4).upper(), "name": str(data["name"]).strip(), "startDate": data["startDate"], "endDate": data["endDate"], "goal": data.get("goal", ""), "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            state.setdefault("sprints", []).insert(0, sprint); write_state(state); self.send_json(201, {"sprint": sprint}); return
        if path == "/api/users":
            claims = self.require_user()
            if not claims: return
            if claims["role"] != "Admin":
                self.send_json(403, {"error": "Only an admin can create login accounts."}); return
            try: data = self.read_json()
            except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
            username = str(data.get("username", "")).strip().lower()
            password = str(data.get("password", ""))
            person = data.get("user") or {}
            if not re.fullmatch(r"[a-z0-9._-]{3,32}", username):
                self.send_json(422, {"error": "Username must be 3–32 letters, numbers, dots, underscores, or hyphens."}); return
            if len(password) < 8:
                self.send_json(422, {"error": "Password must contain at least 8 characters."}); return
            if not person.get("name") or person.get("role") not in {"Admin", "Project Manager", "Developer", "Tester"}:
                self.send_json(422, {"error": "A name and valid role are required."}); return
            salt, digest = password_hash(password)
            try:
                with connect() as db:
                    db.execute("INSERT INTO accounts VALUES(?,?,?,?,?)", (username, salt, digest, person["id"], person["role"]))
                    state_row = db.execute("SELECT json FROM app_state WHERE id=1").fetchone()
                    state = json.loads(state_row["json"]) if state_row else None
                    if state is not None:
                        state.setdefault("users", []).append(person)
                        db.execute("UPDATE app_state SET json=?,updated_at=? WHERE id=1", (json.dumps(state, ensure_ascii=False), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
            except sqlite3.IntegrityError:
                self.send_json(409, {"error": "That username already exists."}); return
            self.send_json(201, {"user": person, "username": username}); return
        match = re.fullmatch(r"/api/issues/([^/]+)/attachments", path)
        if match:
            claims = self.require_user()
            if not claims: return
            issue_id = unquote(match.group(1)); filename = unquote(self.headers.get("X-Filename", "attachment"))[:220]
            try: data = self.read_body()
            except ValueError as exc: self.send_json(413, {"error": str(exc)}); return
            if not data or len(data) > 8 * 1024 * 1024:
                self.send_json(413, {"error": "Choose a file between 1 byte and 8 MB."}); return
            file_id = secrets.token_urlsafe(12); content_type = self.headers.get("Content-Type", "application/octet-stream")
            with connect() as db:
                db.execute("INSERT INTO attachments VALUES(?,?,?,?,?,?,?)", (file_id, issue_id, filename, content_type, len(data), data, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
            self.send_json(201, {"id": file_id, "filename": filename, "size": len(data)}); return
        self.send_json(404, {"error": "API route not found."})

    def do_PUT(self):
        path = urlparse(self.path).path
        issue_match = re.fullmatch(r"/api/issues/([^/]+)", path)
        if issue_match:
            claims = self.require_user()
            if not claims: return
            try: data = self.read_json()
            except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
            if not isinstance(data, dict): self.send_json(422, {"error": "Issue update must be a JSON object."}); return
            state = stored_state() or {}
            item = next((i for i in state.get("issues", []) if i.get("id") == unquote(issue_match.group(1))), None)
            if not item: self.send_json(404, {"error": "Issue not found."}); return
            original = json.loads(json.dumps(state))
            allowed = {"title", "description", "type", "severity", "priority", "module", "workItemKind", "parentId", "referenceUrl", "businessImpact", "assigneeId", "sprintId"}
            item.update({k: v for k, v in data.items() if k in allowed})
            error = validate_state(original, state, claims)
            if error: self.send_json(403 if "Only admins" in error else 422, {"error": error}); return
            record_activity(state, claims, item, "updated issue details")
            write_state(state); self.send_json(200, {"issue": item}); return
        sprint_match = re.fullmatch(r"/api/sprints/([^/]+)/issues", path)
        if sprint_match:
            claims = self.require_user()
            if not claims: return
            if claims["role"] not in ("Admin", "Project Manager"):
                self.send_json(403, {"error": "Only admins and project managers can assign sprint issues."}); return
            try: data = self.read_json()
            except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
            state = stored_state() or {}; sprint_id = unquote(sprint_match.group(1))
            if not any(s.get("id") == sprint_id for s in state.get("sprints", [])):
                self.send_json(404, {"error": "Sprint not found."}); return
            ids = data.get("issueIds", [])
            if not isinstance(ids, list): self.send_json(422, {"error": "issueIds must be an array."}); return
            changed = []
            for item in state.get("issues", []):
                if item.get("id") in ids and item.get("sprintId") != sprint_id:
                    item["sprintId"] = sprint_id; record_activity(state, claims, item, "added this issue to the sprint"); changed.append(item["id"])
            write_state(state); self.send_json(200, {"assigned": changed}); return
        if path != "/api/state":
            self.send_json(404, {"error": "API route not found."}); return
        claims = self.require_user()
        if not claims: return
        try: new = self.read_json()
        except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
        old = stored_state(); error = validate_state(old, new, claims)
        if error:
            self.send_json(403 if "Only admins" in error else 422, {"error": error}); return
        write_state(new)
        self.send_json(200, {"ok": True})

    def do_DELETE(self):
        match = re.fullmatch(r"/api/issues/([^/]+)", urlparse(self.path).path)
        if not match:
            self.send_json(404, {"error": "API route not found."}); return
        claims = self.require_user()
        if not claims: return
        if claims["role"] not in ("Admin", "Project Manager"):
            self.send_json(403, {"error": "Only admins and project managers can delete issues."}); return
        issue_id = unquote(match.group(1))
        state = stored_state() or {}
        item = next((i for i in state.get("issues", []) if i.get("id") == issue_id), None)
        if not item:
            self.send_json(404, {"error": "Issue not found."}); return
        state["issues"] = [i for i in state.get("issues", []) if i.get("id") != issue_id]
        for issue in state["issues"]:
            if issue.get("parentId") == issue_id:
                issue["parentId"] = ""
        for release in state.get("releases", []):
            release["issueIds"] = [ref for ref in release.get("issueIds", []) if ref != issue_id]
        state.setdefault("activity", []).insert(0, {"id": secrets.token_hex(5), "userId": claims["uid"], "text": "deleted issue " + issue_id, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        with connect() as db:
            db.execute("DELETE FROM attachments WHERE issue_id=?", (issue_id,))
        write_state(state)
        self.send_json(200, {"deleted": issue_id})

    def do_PATCH(self):
        match = re.fullmatch(r"/api/issues/([^/]+)/status", urlparse(self.path).path)
        if not match:
            self.send_json(404, {"error": "API route not found."}); return
        claims = self.require_user()
        if not claims: return
        try: data = self.read_json()
        except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
        state = stored_state() or {}; item = next((i for i in state.get("issues", []) if i.get("id") == unquote(match.group(1))), None)
        if not item: self.send_json(404, {"error": "Issue not found."}); return
        destination = data.get("status")
        if destination not in FLOW.get(item.get("status"), set()):
            self.send_json(422, {"error": "Invalid status transition from " + str(item.get("status")) + " to " + str(destination) + "."}); return
        previous = item["status"]; item["status"] = destination
        if destination in ("Resolved", "Closed"):
            item["resolutionAt"] = item.get("resolutionAt") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        elif previous in ("Resolved", "Closed"):
            item.pop("resolutionAt", None)
        record_activity(state, claims, item, "moved this issue from " + previous + " to " + destination); write_state(state)
        self.send_json(200, {"issue": item})

    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Allow", "GET, POST, PUT, PATCH, DELETE, OPTIONS"); self.end_headers()

    def serve_static(self, requested: str):
        target = (ROOT / ("index.html" if requested in ("", "/") else requested.lstrip("/"))).resolve()
        if ROOT not in target.parents and target != ROOT:
            self.send_json(403, {"error": "Forbidden."}); return
        if not target.is_file():
            self.send_json(404, {"error": "File not found."}); return
        body = target.read_bytes(); mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200); self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or "javascript" in mime else "")); self.send_header("Content-Length", str(len(body))); self.send_header("X-Content-Type-Options", "nosniff"); self.end_headers(); self.wfile.write(body)


if __name__ == "__main__":
    initialize()
    host = os.environ.get("BUGFLOW_HOST", "127.0.0.1")
    port = int(os.environ.get("BUGFLOW_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), Handler)
    print("BugFlow serving at http://%s:%s" % (host, port))
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

