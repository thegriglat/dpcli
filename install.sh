#!/usr/bin/env bash
# Install or update dpcli in an existing git project (run in the project):
#   curl -fsSL https://raw.githubusercontent.com/thegriglat/dpcli/main/install.sh | bash
#   bash install.sh [--lang ru] [--commit-lang en] [--ref vN|branch] [--tools] [--yes]
# Idempotent. Copies the distribution into .dpcli (a plain folder committed with the project; no submodule),
# config (language), runs init. Update = run it again. Own agents left in .dpcli/agents go to .dpcli-local/agents;
# a .dpcli submodule is converted to a folder. Never commits.
set -euo pipefail

REPO="${DPCLI_REPO:-https://github.com/thegriglat/dpcli.git}"
REF="${DPCLI_REF:-}"
LANG_TEXT="" LANG_COMMITS="" TOOLS=0 YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --lang) LANG_TEXT="$2"; shift 2 ;;
    --commit-lang) LANG_COMMITS="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --tools) TOOLS=1; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "install: unknown option $1" >&2; exit 2 ;;
  esac
done

die() { echo "install: $*" >&2; exit 1; }
say() { echo "dpcli: $*"; }

root=$(git rev-parse --show-toplevel 2>/dev/null) || die "run inside a git repository"
cd "$root"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null || die "Python ≥ 3.10 is required"

ask() {  # ask VAR "question" default — reads the terminal even under curl | bash
  local cur="${!1}"
  if [ -z "$cur" ] && [ "$YES" = 0 ] && { exec 3</dev/tty; } 2>/dev/null; then
    read -r -u 3 -p "$2 [$3]: " cur || true
    exec 3<&-
  fi
  printf -v "$1" '%s' "${cur:-$3}"
}
ask LANG_TEXT "Language agents write in for people (replies, reports, plans, docs): en, ru, de, …" en
ask LANG_COMMITS "Language of commit messages" en

# ---- the distribution: latest release tag (or --ref, or the default branch) copied into .dpcli
DIST_FILES="dpcli install.sh lib agents hooks skills templates dpcli.example.yml README.md CHANGELOG.md LICENSE"
wipe() { case "$1" in .dpcli|"$tmp"|"$(git rev-parse --git-dir)/modules/.dpcli") [ ! -e "$1" ] || rm -r -- "$1" ;; *) die "refusing to delete $1" ;; esac; }
tmp=$(mktemp -d); trap 'chmod -R u+w "$tmp" 2>/dev/null; wipe "$tmp"' EXIT
git clone -q "$REPO" "$tmp/src" || die "cannot clone $REPO"
[ -n "$REF" ] || REF=$(git -C "$tmp/src" tag -l 'v*' | sort -V | tail -1)
[ -n "$REF" ] && { git -C "$tmp/src" checkout -q "$REF" || die "no ref $REF in $REPO"; }
latest=$(sed -n 's/^VERSION *= *\([0-9]*\).*/v\1/p' "$tmp/src/lib/dpcli/__init__.py")

[ -z "$(git status --porcelain -- .dpcli 2>/dev/null)" ] || die "uncommitted changes in .dpcli would be lost — commit or discard them (project changes belong in .dpcli-local/)"
if git ls-files -s .dpcli | grep -q '^160000'; then  # a submodule (also without .gitmodules) → a plain folder
  git rm -q --cached .dpcli
  [ -f .gitmodules ] && git config -f .gitmodules --remove-section submodule..dpcli 2>/dev/null && git add .gitmodules
  wipe .dpcli; wipe "$(git rev-parse --git-dir)/modules/.dpcli"
  say "submodule .dpcli converted to a folder"
elif [ -e .dpcli ] && [ -z "$(git ls-files .dpcli | head -1)" ] && [ ! -x .dpcli/dpcli ]; then
  die ".dpcli exists but is not dpcli — move it away and rerun"
fi
[ -d .dpcli ] || { [ -n "$(git ls-files .dpcli | head -1)" ] && git checkout -q -- .dpcli; } || true  # deleted from disk
if [ -d .dpcli/agents ]; then  # own agents dropped into the distribution survive in the project layer
  mkdir -p .dpcli-local/agents
  for f in .dpcli/agents/*.md; do
    [ -e "$f" ] || continue
    n=$(basename "$f")
    if [ ! -e "$tmp/src/agents/$n" ] && [ ! -e ".dpcli-local/agents/$n" ]; then
      cp "$f" ".dpcli-local/agents/$n"; say "own agent $n → .dpcli-local/agents/"
    fi
  done
fi
wipe .dpcli && mkdir .dpcli
for f in $DIST_FILES; do [ -e "$tmp/src/$f" ] && cp -R "$tmp/src/$f" .dpcli/; done
say "version $latest${REF:+ ($REF)}"

# ---- config: created by init from the example; then language; the old submodule worktree setup is dropped
[ -e dpcli.yml ] || [ -e dpcli.json ] || [ -e dpcli.yaml ] || .dpcli/dpcli init >/dev/null
python3 - "$LANG_TEXT" "$LANG_COMMITS" <<'PY'
import json, re, sys
from pathlib import Path
text, commits = sys.argv[1], sys.argv[2]
for name in ("dpcli.json", "dpcli.yml", "dpcli.yaml"):
    p = Path(name)
    if p.is_file():
        break
if p.suffix == ".json":
    d = json.loads(p.read_text() or "{}")
    d.setdefault("language", {}).update({"text": text, "commits": commits})
    if d.get("worktree", {}).get("setup") == "git submodule update --init .dpcli":
        del d["worktree"]["setup"]
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    sys.exit()
t = p.read_text()
lang = f"language:\n  text: {text}\n  commits: {commits}\n"
if re.search(r"^language:\s*$", t, re.M):
    t = re.sub(r"^language:\s*\n(?:[ \t]+.*\n?)*", lang, t, count=1, flags=re.M)
else:
    t = t.rstrip("\n") + "\n\n" + lang
t = re.sub(r'^[ \t]+setup:[ \t]*"?git submodule update --init \.dpcli"?[ \t]*\n', "", t, flags=re.M)
p.write_text(t)
PY
.dpcli/dpcli init >/dev/null
say "init done (agents, skills, process, CLAUDE.md block, permissions, hooks)"

# ---- fast tools for agents
missing=()
for t in rg fd jq ast-grep; do
  command -v "$t" >/dev/null 2>&1 || { [ "$t" = fd ] && command -v fdfind >/dev/null 2>&1; } || missing+=("$t")
done
if [ ${#missing[@]} -gt 0 ] && [ "$TOOLS" = 1 ]; then
  sudo=""; [ "$(id -u)" = 0 ] || sudo="sudo"
  if command -v brew >/dev/null; then
    brew install $(printf '%s\n' "${missing[@]}" | sed 's/^rg$/ripgrep/') || true
  elif command -v apt-get >/dev/null; then
    pk=(); for t in "${missing[@]}"; do case $t in rg) pk+=(ripgrep);; fd) pk+=(fd-find);; jq) pk+=(jq);; esac; done
    if [ ${#pk[@]} -gt 0 ] && ! $sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${pk[@]}" >/dev/null 2>&1; then
      say "apt-get install ${pk[*]} failed (run it by hand to see why)"
    fi
    command -v fdfind >/dev/null && ! command -v fd >/dev/null && mkdir -p ~/.local/bin && ln -sf "$(command -v fdfind)" ~/.local/bin/fd
  fi
  if [[ " ${missing[*]} " == *" ast-grep "* ]] && ! command -v ast-grep >/dev/null; then
    if command -v uv >/dev/null; then uv tool install -q ast-grep-cli || true
    elif command -v npm >/dev/null; then npm i -g --silent @ast-grep/cli || true; fi
  fi
  missing=(); for t in rg fd jq ast-grep; do command -v "$t" >/dev/null 2>&1 || missing+=("$t"); done
fi
[ ${#missing[@]} -gt 0 ] && say "missing fast tools for agents: ${missing[*]} (rerun with --tools to install)"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *)
  { [ -x "$HOME/.local/bin/fd" ] || [ -x "$HOME/.local/bin/ast-grep" ]; } && say "add ~/.local/bin to PATH: fd / ast-grep are there" ;; esac

paths=".gitmodules .dpcli dpcli.yml dpcli.json dpcli.yaml .dpcli-local .claude CLAUDE.md .gitignore"
changed=$(git status --porcelain -- $paths 2>/dev/null || true)
if [ -n "$changed" ]; then
  echo "$changed"
  existing=$(for p in $paths; do [ -e "$p" ] && printf '%s ' "$p"; done)
  echo "commit: git add -- $existing&& git commit -m \"dpcli $latest\" -- $existing"
else
  say "nothing changed"
fi
