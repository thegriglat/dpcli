# Security

dpcli runs inside your project with your permissions: its hooks (`hooks/*.py`) and commands are plain Python you can read. It never updates itself: a new version arrives only when you run `install.sh`, and you review and commit the diff of `.dpcli/` like any other change. Pin a version with `--ref vN`.

## Reporting a vulnerability

Do not open a public issue. Use GitHub's private vulnerability reporting (*Security → Report a vulnerability*) on this repository.
