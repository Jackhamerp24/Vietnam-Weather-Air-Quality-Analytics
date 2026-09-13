"""Tests for Phase 11 operator-file parsing and explicit child environments."""

import os
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_automation as launcher

from vn_air.automation_environment import (
    OperatorEnvironmentError,
    ingestion_environment,
    read_operator_environment,
)


class AutomationEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.checkout = self.base / "checkout"
        self.checkout.mkdir(mode=0o700)

    def write_env(self, name, content, mode=0o600):
        path = self.base / name
        path.write_text(content, encoding="utf-8")
        path.chmod(mode)
        return path

    def test_literal_operator_file(self):
        path = self.write_env("operator.env", "# comment\nDATABASE_URL=postgresql://u@localhost/db\nOPENAQ_API_KEY=key\n")
        self.assertEqual(read_operator_environment(path, checkout=self.checkout), {
            "DATABASE_URL": "postgresql://u@localhost/db",
            "OPENAQ_API_KEY": "key",
        })

    def test_operator_file_rejects_unknown_duplicate_and_shell_values(self):
        cases = {
            "unknown.env": "DATABASE_URL=x\nOPENAQ_API_KEY=y\nUNRELATED_SECRET=z\n",
            "duplicate.env": "DATABASE_URL=x\nDATABASE_URL=y\nOPENAQ_API_KEY=z\n",
            "shell.env": "DATABASE_URL=$(touch /tmp/phase11-canary)\nOPENAQ_API_KEY=y\n",
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(OperatorEnvironmentError):
                    read_operator_environment(self.write_env(name, content), checkout=self.checkout)

    def test_operator_file_requires_owner_only_mode_and_both_values(self):
        with self.assertRaises(OperatorEnvironmentError):
            read_operator_environment(self.write_env("wide.env", "DATABASE_URL=x\nOPENAQ_API_KEY=y\n", 0o644),
                                      checkout=self.checkout)
        with self.assertRaises(OperatorEnvironmentError):
            read_operator_environment(self.write_env("missing.env", "DATABASE_URL=x\n"), checkout=self.checkout)
        with self.assertRaises(OperatorEnvironmentError):
            read_operator_environment(self.write_env(".env", "DATABASE_URL=x\nOPENAQ_API_KEY=y\n"),
                                      checkout=self.checkout)

    def test_operator_file_must_be_outside_checkout_and_non_symlink(self):
        inside = self.checkout / "operator.env"
        inside.write_text("DATABASE_URL=x\nOPENAQ_API_KEY=y\n", encoding="utf-8")
        inside.chmod(0o600)
        with self.assertRaises(OperatorEnvironmentError):
            read_operator_environment(inside, checkout=self.checkout)
        link = self.base / "link.env"
        link.symlink_to(self.write_env("real.env", "DATABASE_URL=x\nOPENAQ_API_KEY=y\n"))
        with self.assertRaises(OperatorEnvironmentError):
            read_operator_environment(link, checkout=self.checkout)

    def test_ingestion_environment_drops_unrelated_and_dynamic_loader_values(self):
        source = self.checkout / "src"
        environment = ingestion_environment({
            "DATABASE_URL": "postgresql://u@localhost/db",
            "OPENAQ_API_KEY": "key",
            "PATH": "/usr/bin",
            "UNRELATED_SECRET": "drop",
            "UNRELATED_TOKEN": "drop",
            "SUPABASE_SECRET_KEY": "drop",
            "PGSERVICE": "drop",
            "PYTHONSTARTUP": "drop",
            "DYLD_INSERT_LIBRARIES": "drop",
        }, source)
        self.assertEqual(environment["PYTHONPATH"], str(source))
        self.assertEqual(environment["DATABASE_URL"], "postgresql://u@localhost/db")
        self.assertEqual(environment["OPENAQ_API_KEY"], "key")
        for name in ("UNRELATED_SECRET", "UNRELATED_TOKEN", "SUPABASE_SECRET_KEY",
                     "PGSERVICE", "PYTHONSTARTUP", "DYLD_INSERT_LIBRARIES"):
            self.assertNotIn(name, environment)

    def test_launcher_execs_clean_environment_with_no_secret_arguments(self):
        path = self.write_env("launcher.env", "DATABASE_URL=postgresql://u@localhost/db\nOPENAQ_API_KEY=key\n")
        output = (self.base / "cycles").resolve()
        class ExecReached(BaseException):
            pass
        with patch.object(launcher, "ROOT", self.checkout), patch.object(launcher.os, "chdir"), \
                patch.object(launcher.os, "execve", side_effect=ExecReached) as execute, \
                patch.dict(os.environ, {"UNRELATED_SECRET": "unrelated-secret-canary"}):
            with self.assertRaises(ExecReached):
                launcher.main(["--env-file", str(path), "--output-root", str(output)])
        executable, argv, environment = execute.call_args.args
        self.assertEqual(executable, argv[0])
        self.assertEqual(environment["OPENAQ_API_KEY"], "key")
        self.assertNotIn("UNRELATED_SECRET", environment)
        self.assertNotIn(environment["DATABASE_URL"], " ".join(argv))
        self.assertFalse(Path(argv[-1]).exists())  # The cycle itself reserves it.

    def test_launcher_rejects_unknown_keys_before_output_or_exec(self):
        path = self.write_env("reject.env", "DATABASE_URL=x\nOPENAQ_API_KEY=y\nUNRELATED_SECRET=secret-canary\n")
        output = self.base / "not-created"
        stderr = io.StringIO()
        with patch.object(launcher, "ROOT", self.checkout), \
                patch.object(launcher.os, "execve") as execute, contextlib.redirect_stderr(stderr):
            self.assertEqual(launcher.main(["--env-file", str(path), "--output-root", str(output)]), 3)
        execute.assert_not_called()
        self.assertFalse(output.exists())
        self.assertNotIn("secret-canary", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
