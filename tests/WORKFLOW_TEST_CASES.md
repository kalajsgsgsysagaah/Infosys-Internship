# Workflow and quality test cases

Use the local demo at `http://localhost:8080` and the seeded accounts in the project README. These checks cover the integrated issue lifecycle and should be run again after frontend or server changes.

| ID | Area | Steps | Expected result |
|---|---|---|---|
| TC-01 | Classification and persistence | Create an issue with a type, severity, priority, module, business impact, and assignee. Open the issue list, then reload the page. | The list shows type, severity, priority, status, module, and assignee; all fields remain after reload. |
| TC-02 | Work hierarchy and code reference | Create an Epic, then create a Task linked to it and attach an HTTPS code or pull request link. Open the Task details. | The parent relationship and safe code link appear in details and are retained after reload. |
| TC-03 | Comments and activity | Add a comment to an issue, then inspect its details and the activity feed. | The comment shows the signed-in author and timestamp; activity records the comment. |
| TC-04 | Attachments | Upload a small screenshot or log file to an issue, then download it from the attachment list. | The attachment persists, downloads with its filename, and the activity history records the upload. |
| TC-05 | Assignment and escalation | As Admin or Project Manager, reassign an issue and use “Escalate to Critical / P1”. | The updated owner and severity/priority are saved, and both actions appear in issue history. |
| TC-06 | Backlog and sprint planning | Create a sprint with valid dates, select backlog issues, assign them to the sprint, and open its board. | Sprint dates and goal are saved; work appears under To Do, In Progress, or Done based on status. |
| TC-07 | Workflow validation | Move an issue through Open → In Progress → Testing → Resolved → Closed. Separately attempt Open → Testing through the API. | Valid transitions succeed and are recorded; the skipped transition is rejected without changing the issue. |
| TC-08 | Release readiness | Create a release and link several issues, including an unresolved Critical issue. | Linked issues appear in the release card and the critical blocker reduces readiness. |
| TC-09 | Analytics, exports, and API | Compare dashboard and analytics counts with the issue list; export CSV and JSON; request the authenticated issue and sprint APIs. | Counts match saved workspace data; exports include the expected records; unauthenticated API requests are rejected. |
| TC-10 | Roles and regression | Sign in as each seeded role, verify role-gated team/sprint actions, then revisit the dashboard, issue list, releases, and reports. | Only permitted actions are accepted, and core issue-tracking features continue to work across roles. |
| TC-11 | Dialog close controls | Open issue, sprint, release, account, and activity dialogs. Close each using its × button; also try Cancel, Close, and clicking outside the dialog. | Every ×, Cancel, Close, and backdrop control dismisses the dialog; clicking inside the dialog does not dismiss it. |
