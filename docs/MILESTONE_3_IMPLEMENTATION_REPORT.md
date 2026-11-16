# BugFlow Milestone 3 Implementation Report

## Scope delivered

| Milestone area | BugFlow implementation |
| --- | --- |
| REST API development | Authenticated issue list/create/read/update/delete routes; status transition, comments, attachments, sprint assignment, and health routes. Data is persisted in SQLite. |
| API testing and reporting | Importable Postman collection covers login, issue CRUD, sprint assignment, transition validation, analytics, and module-filtered reports. |
| Project analytics | Status and severity totals, module counts, pending/resolved counts, resolution duration where recorded, and release readiness. |
| Admin dashboard and defect charts | Workspace summary, status pie chart, severity bar chart, and monthly created/resolved trend. |
| GitHub integration | GitHub profile link, commit/PR URL fields in issue details, and a signed webhook for linked issue status synchronization. |
| CI/CD | GitHub Actions runs syntax checks and automated tests on pushes and pull requests; optional webhook step syncs issue status from the workflow result. |
| Documentation | Setup, usage walkthrough, API setup, and evaluation limitations are in the project README. |

## API routes

- `GET /api/issues` and `GET /api/issues/{id}`
- `POST /api/issues`, `PUT /api/issues/{id}`, and `DELETE /api/issues/{id}`
- `PATCH /api/issues/{id}/status`
- `POST /api/issues/{id}/comments`
- `GET /api/analytics/summary`, `GET /api/analytics/quality`, and `GET /api/reports/project?module=API`
- `GET /api/sprints`, `POST /api/sprints`, and `PUT /api/sprints/{id}/issues`
- `POST /api/integrations/github/status` (HMAC SHA-256 signature required)

All API routes except `GET /api/health` require a bearer token. Issue deletion and sprint assignment are restricted to admins and project managers. Workflow changes are validated on the server.

## Local walkthrough

Start `run.bat`, open `http://localhost:8080`, then sign in as `gaurav` / `admin123`. Import and run `postman/BugFlow-Milestone-3.postman_collection.json` in Postman to produce the API test run summary. The collection creates a temporary issue and deletes it at the end.

## GitHub status sync setup

Deploy BugFlow at a public HTTPS URL. Set `BUGFLOW_WEBHOOK_SECRET` in the server environment. In the GitHub repository settings, add a `BUGFLOW_WEBHOOK_URL` variable and a matching `BUGFLOW_WEBHOOK_SECRET` secret. Commit messages and pull-request title/body text must include issue identifiers such as `BF-1042`. Passing checks move linked `In Progress` issues to `Testing`; failed checks return linked `Testing` issues to `In Progress`.

## Evaluation notes

The app reports defect counts by module. A normalized defect-density measure needs module size data, such as source lines of code, which is not tracked in this project. The presentation's 300 ms p95 response-time and 99% data-consistency criteria require load and consistency measurements; no results are claimed here. Run the documented checks and Postman collection before submitting evaluation evidence.
