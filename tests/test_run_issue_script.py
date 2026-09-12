"""Static and pure-function checks for the local runner; no network or agent calls."""

from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "run-issue.ps1"


class LocalIssueRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_required_parameter_and_fail_closed_ordering(self):
        self.assertRegex(self.source, r"\[Parameter\(Mandatory = \$true, Position = 0\)\]")
        self.assertRegex(self.source, r"\[int\]\$IssueNumber")
        clean = self.source.index("Assert-CleanWorkingTree -GitCommand $git")
        fetch = self.source.index('@("fetch", "origin", "main")')
        switch = self.source.index('@("switch", "main")')
        self.assertLess(clean, fetch)
        self.assertLess(clean, switch)
        self.assertIn('merge", "--ff-only", "origin/main', self.source)

    def test_issue_branch_and_pr_contracts_are_explicit(self):
        for required in (
            '"agent/issue-$IssueNumber"',
            '@("issue", "view", [string]$IssueNumber',
            '@("show-ref", "--verify", "--quiet", "refs/heads/$Name")',
            '@("ls-remote", "--exit-code", "--heads", "origin", "refs/heads/$Name")',
            "gh pr create",
            "Closes #$IssueNumber",
            "Human review and merge are required",
        ):
            self.assertIn(required, self.source)
        self.assertNotRegex(self.source, r"\bgh\s+pr\s+merge\b")

    def test_codex_uses_saved_login_and_bounded_noninteractive_flags(self):
        for required in (
            "codex.cmd",
            '@("login", "status")',
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox workspace-write",
            "--approve-for-me",
            "sandbox_workspace_write.network_access=false",
            "-C $RepositoryRoot -",
        ):
            self.assertIn(required, self.source)
        self.assertNotIn("--with-api-key", self.source)
        self.assertNotRegex(self.source, r"\$env:(OPENAI_API_KEY|CODEX_API_KEY)\s*=")

    def test_validation_and_publication_order(self):
        codex = self.source.index("$task | & $codex exec")
        tests = self.source.index('@("-B", "-m", "unittest", "discover"')
        whitespace = self.source.index('@("diff", "--check")')
        push = self.source.index('@("push", "--set-upstream"')
        pull_request = self.source.index("& $gh pr create")
        self.assertLess(codex, tests)
        self.assertLess(tests, whitespace)
        self.assertLess(whitespace, push)
        self.assertLess(push, pull_request)

    def test_no_mailbox_or_existing_workflow_execution(self):
        self.assertNotIn("gmail_storage_auditor.gmail_cli", self.source)
        self.assertNotIn(".github/workflows/codex-issue-orchestrator.yml", self.source)
        self.assertIn("Do not access Gmail, a real mailbox", self.source)
        self.assertIn("Do not call Gmail APIs or perform any mailbox mutation", self.source)

    @unittest.skipUnless(shutil.which("powershell.exe"), "PowerShell is unavailable")
    def test_task_builder_and_dirty_status_guard_without_external_commands(self):
        command = rf"""
. '{SCRIPT}' -IssueNumber 16
$task = New-CodexTask -Number 16 -Title 'Synthetic title' -Body 'Synthetic body' -Url 'https://example.invalid/16'
if ($task -notmatch 'Synthetic title' -or $task -notmatch 'Synthetic body') {{ exit 2 }}
if ($task -notmatch 'Use synthetic fixtures only') {{ exit 3 }}
try {{ Assert-CleanStatus -StatusLines @('?? local.txt'); exit 4 }} catch {{}}
Assert-CleanStatus -StatusLines @()
"""
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
