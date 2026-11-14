# BugFlow · Issue tracking and resolution

This folder contains the BugFlow website and Python application server. It combines the core issue-tracking platform with workflow automation, collaboration, sprint planning, and quality reporting.

## Run locally

Double-click `run.bat`. It starts `server.py` and serves the site and API at:

```powershell
python server.py
```

Then open <http://localhost:8080>.

## Included workflows

- Dashboard with defect trends, project health, sprint progress, and activity.
- Issue creation with type, severity, priority, affected module, business impact, and assignee.
- Work item hierarchy for epics, stories, and tasks, plus optional code, commit, or pull request links.
- Issue escalation to Critical / P1 with a recorded activity event.
- Issue list with search and filters; CSV and JSON exports.
- Issue detail view with comments, timestamps, attachment upload/download, and activity history.
- Backlog selection, sprint creation, issue assignment, and a To Do / In Progress / Done board.
- Enforced lifecycle transitions: Open → In Progress → Testing → Resolved → Closed. Testing can return to In Progress, and Resolved can be reopened to In Progress.
- Release readiness, analytics, reports, role-based team access, and a REST/CI/CD integration reference.
- APIs for issue and comment management, workflow transitions, sprint planning, analytics, and attachments; Docker and GitHub Actions support packaging and CI checks.

## Accounts for the local demo

The first sign-in bootstraps a local SQLite database (`bugflow.sqlite3`). Use any of these demo accounts:

| Role | Username | Password |
|---|---|---|
| Admin | `gaurav` | `admin123` |
| Project Manager | `maya` | `manager123` |
| Developer | `arjun` | `dev123` |
| Tester | `neha` | `tester123` |

## Persistence and security

Issues, comments, sprints, releases, users, and activity are persisted in SQLite. The server uses signed, expiring bearer tokens, password hashes, role checks, upload size limits, and server-side workflow validation. Attachments are stored in SQLite.

## API and deployment

The Python server exposes authenticated REST routes for issue creation, lookup, update (`PUT /api/issues/{id}`), deletion (`DELETE /api/issues/{id}`), comments, status transitions, sprint planning and assignment, analytics, and attachments. `GET /api/analytics/quality` and `GET /api/reports/project?module=API` return status, severity, module, pending-work, and average-resolution-time metrics. `GET /api/health` is available for readiness checks. The HTML client uses the same-origin API and saves workspace changes to SQLite.

The integrations page links to the project owner's [GitHub profile](https://github.com/kalajsgsgsysagaah). Add a commit or pull-request URL to an issue's Code reference field to associate development work with that issue. GitHub Actions runs the repository's automated checks on pushes and pull requests. Optional signed status synchronization is available at `POST /api/integrations/github/status`: set `BUGFLOW_WEBHOOK_SECRET` on the server, then configure the GitHub Actions `BUGFLOW_WEBHOOK_URL` repository variable and matching `BUGFLOW_WEBHOOK_SECRET` secret. Commit messages or pull-request text containing issue IDs such as `BF-1042` are synced: successful checks move `In Progress` issues to `Testing`, and failed checks move `Testing` issues back to `In Progress`. This local workspace has no public webhook URL configured.

Run backend checks with `python -m unittest discover -s tests -v` and dialog-control checks with `node --test tests/modal_controls.test.cjs`. Build and run the container with `docker build -t bugflow .` and `docker run --rm -p 8080:8080 -v bugflow-data:/data bugflow`. The GitHub Actions workflow checks Python and JavaScript syntax and runs both test suites.

The manual acceptance scenarios for classification, collaboration, attachments, sprint and release planning, lifecycle rules, analytics, APIs, and role permissions are in [`tests/WORKFLOW_TEST_CASES.md`](tests/WORKFLOW_TEST_CASES.md).

This is a local Python implementation of the brief’s authentication and REST requirements, using signed expiring bearer tokens instead of Spring Security/JWT. Change the demo passwords before exposing the server to a network. The Docker and GitHub Actions files provide packaging and CI; production deployment still needs environment-specific secret management, HTTPS, backups, and hosting configuration.

To start the demo from its original seeded state, clear this site's browser storage for `localhost:8080` (localStorage key `bugflow-milestone-suite-v1` and IndexedDB database `bugflow-attachments-v1`).
