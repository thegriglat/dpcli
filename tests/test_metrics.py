"""Lightness budgets hold for the distribution itself (the same check CI runs on every PR)."""
import subprocess
import sys
import unittest

from helpers import REPO


class Budgets(unittest.TestCase):
    def test_within_budgets(self):
        r = subprocess.run([sys.executable, str(REPO / "tools" / "metrics.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
