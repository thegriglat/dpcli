"""merge --into a branch no copy has open: a fast-forward moves the ref without a checkout, anything else is refused."""
import unittest

from helpers import Project, git


class MergeNoCopy(unittest.TestCase):
    def test_fast_forward_without_a_copy(self):
        p = Project()
        self.addCleanup(p.cleanup)
        r = p.root
        base = git("rev-parse", "HEAD", cwd=r)
        for br in ("feat", "other"):
            git("switch", "-q", "-c", br, base, cwd=r)
            (r / f"{br}.txt").write_text(br)
            git("add", f"{br}.txt", cwd=r)
            git("commit", "-q", "-m", br, cwd=r)
        git("switch", "-q", "feat", cwd=r)  # main is open nowhere (the copy cannot switch to it)
        self.assertIn("fast-forward", p.ok("merge", "feat", "--into", "main"))
        self.assertEqual(git("rev-parse", "main", cwd=r), git("rev-parse", "feat", cwd=r))
        code, _, err = p.run("merge", "other", "--into", "main")  # diverged: needs a real merge
        self.assertEqual(code, 1)
        self.assertIn("not a fast-forward", err)
        self.assertEqual(git("rev-parse", "main", cwd=r), git("rev-parse", "feat", cwd=r))


if __name__ == "__main__":
    unittest.main()
