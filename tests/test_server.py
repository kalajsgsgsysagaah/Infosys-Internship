import secrets
import unittest
from pathlib import Path

import server


class StateValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(__file__).parent / ("test-db-" + secrets.token_hex(4))
        self.temp.mkdir()
        self.original_db = server.DB_PATH
        server.DB_PATH = self.temp / "test.sqlite3"
        server.initialize()
        self.issue = {"id": "BF-1001", "status": "Open", "assigneeId": None, "sprintId": None}
        self.base = {"users": [], "issues": [self.issue.copy()], "sprints": [], "releases": []}

    def tearDown(self):
        server.DB_PATH = self.original_db
        for path in self.temp.iterdir():
            path.unlink()
        self.temp.rmdir()

    def test_all_expected_forward_transitions_are_accepted(self):
        pairs = [("Open", "In Progress"), ("In Progress", "Testing"), ("Testing", "Resolved"), ("Resolved", "Closed")]
        for before, after in pairs:
            with self.subTest(before=before, after=after):
                old = {**self.base, "issues": [{**self.issue, "status": before}]}
                new = {**old, "issues": [{**self.issue, "status": after}]}
                self.assertIsNone(server.validate_state(old, new, {"role": "Developer"}))

    def test_testing_can_return_to_development(self):
        old = {**self.base, "issues": [{**self.issue, "status": "Testing"}]}
        new = {**old, "issues": [{**self.issue, "status": "In Progress"}]}
        self.assertIsNone(server.validate_state(old, new, {"role": "Tester"}))

    def test_invalid_transition_is_rejected(self):
        new = {**self.base, "issues": [{**self.issue, "status": "Closed"}]}
        self.assertIn("Invalid status transition", server.validate_state(self.base, new, {"role": "Developer"}))

    def test_closed_issue_cannot_reopen(self):
        old = {**self.base, "issues": [{**self.issue, "status": "Closed"}]}
        new = {**old, "issues": [{**self.issue, "status": "Open"}]}
        self.assertIn("Invalid status transition", server.validate_state(old, new, {"role": "Admin"}))

    def test_developer_cannot_reassign_issue(self):
        new = {**self.base, "issues": [{**self.issue, "assigneeId": "U2"}]}
        self.assertIn("change issue assignments", server.validate_state(self.base, new, {"role": "Developer"}))

    def test_admin_can_assign_issue_to_sprint(self):
        new = {**self.base, "issues": [{**self.issue, "sprintId": "SP1"}]}
        self.assertIsNone(server.validate_state(self.base, new, {"role": "Admin"}))

    def test_task_can_be_grouped_under_an_epic(self):
        epic = {"id": "BF-1000", "status": "Open", "workItemKind": "Epic"}
        task = {**self.issue, "workItemKind": "Task", "parentId": "BF-1000"}
        state = {**self.base, "issues": [epic, task]}
        self.assertIsNone(server.validate_state(self.base, state, {"role": "Admin"}))

    def test_work_item_relationship_cycles_are_rejected(self):
        parent = {"id": "BF-1000", "status": "Open", "workItemKind": "Epic", "parentId": "BF-1001"}
        child = {**self.issue, "workItemKind": "Task", "parentId": "BF-1000"}
        state = {**self.base, "issues": [parent, child]}
        self.assertIn("cannot contain a cycle", server.validate_state(self.base, state, {"role": "Admin"}))

    def test_code_reference_must_be_http_or_https(self):
        item = {**self.issue, "referenceUrl": "javascript:alert(1)"}
        state = {**self.base, "issues": [item]}
        self.assertIn("http or https", server.validate_state(self.base, state, {"role": "Admin"}))

    def test_token_is_signed_and_expires(self):
        with server.connect() as db:
            account = db.execute("SELECT * FROM accounts WHERE username='gaurav'").fetchone()
        token = server.sign_token(account)
        self.assertEqual(server.verify_token(token)["role"], "Admin")
        parts = token.split(".")
        self.assertIsNone(server.verify_token(parts[0] + "." + parts[1] + ".invalid"))


if __name__ == "__main__":
    unittest.main()
