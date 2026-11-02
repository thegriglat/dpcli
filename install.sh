#!/usr/bin/env bash
# Install or update dpcli in an existing git project (run in the project):
#   curl -fsSL https://raw.githubusercontent.com/zolotarev/dpcli/main/install.sh | bash
#   bash install.sh [--lang ru] [--commit-lang en] [--tools] [--yes]
# Idempotent. Adds the submodule .dpcli at the latest release, config (language, worktree setup), runs init.
# Migrates a vendored (copied) .dpcli: own agents go to .dpcli-local/agents. Never commits.
set -euo pipefail

REPO="${DPCLI_REPO:-https://github.com/zolotarev/dpcli.git}"
LANG_TEXT="" LANG_COMMITS="" TOOLS=0 YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --lang) LANG_TEXT="$2"; shift 2 ;;
    --commit-lang) LANG_COMMITS="$2"; shift 2 ;;
    --tools) TOOLS=1; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
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

# ---- the submodule
if git config -f .gitmodules --get submodule..dpcli.path >/dev/null 2>&1; then
  git submodule update --init .dpcli
  say "submodule .dpcli present"
elif git ls-files -s .dpcli | grep -q '^160000'; then
  # recorded as a submodule but missing from .gitmodules (or never initialized): register it and check it out
  git config -f .gitmodules submodule..dpcli.path .dpcli
  git config -f .gitmodules submodule..dpcli.url "$REPO"
  git add .gitmodules
  if ! git submodule update --init .dpcli 2>/dev/null; then
    git rm -q --cached .dpcli; rmdir .dpcli 2>/dev/null || true  # an empty uninitialized dir only
    git submodule add -q --force "$REPO" .dpcli
  fi
  say "submodule .dpcli registered from $REPO"
elif [ -n "$(git ls-files .dpcli | head -1)" ]; then
  # vendored copy; deleted from disk — restore it from the index first so own agents can be carried over
  [ -d .dpcli ] || git checkout -q -- .dpcli
  backup="$(git rev-parse --git-dir)/dpcli-vendored-$(date +%Y%m%d%H%M%S)"
  mv .dpcli "$backup"
  git rm -r -q --cached .dpcli
  git submodule add -q "$REPO" .dpcli
  mkdir -p .dpcli-local/agents
  for f in "$backup"/agents/*.md; do
    [ -e "$f" ] || continue
    n=$(basename "$f")
    if [ ! -e ".dpcli/agents/$n" ]; then
      cp "$f" ".dpcli-local/agents/$n"; say "own agent $n → .dpcli-local/agents/"
    elif ! cmp -s "$f" ".dpcli/agents/$n"; then
      say "agent $n differs from the new version — not carried over; your old copy: $backup/agents/$n (additions → .dpcli-local/agents/${n%.md}.append.md)"
    fi
  done
  say "vendored .dpcli replaced by the submodule (old copy: $backup)"
elif [ -e .dpcli ]; then
  die ".dpcli exists but is not tracked — move it away and rerun"
else
  git submodule add -q "$REPO" .dpcli
  say "submodule .dpcli added from $REPO"
fi
latest=$(git -C .dpcli tag -l 'v*' | sort -V | tail -1)
[ -n "$latest" ] && git -C .dpcli checkout -q "$latest" && say "version $latest"

# ---- config: created by init from the example; then language and worktree setup if missing
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
    d.setdefault("worktree", {}).setdefault("setup", "git submodule update --init .dpcli")
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    sys.exit()
t = p.read_text()
lang = f"language:\n  text: {text}\n  commits: {commits}\n"
if re.search(r"^language:\s*$", t, re.M):
    t = re.sub(r"^language:\s*\n(?:[ \t]+.*\n?)*", lang, t, count=1, flags=re.M)
else:
    t = t.rstrip("\n") + "\n\n" + lang
if not re.search(r"^\s+setup:\s*\S", t, re.M):
    if re.search(r"^worktree:\s*$", t, re.M):
        t = re.sub(r"^worktree:\s*$", 'worktree:\n  setup: "git submodule update --init .dpcli"', t, count=1, flags=re.M)
    else:
        t = t.rstrip("\n") + '\n\nworktree:\n  setup: "git submodule update --init .dpcli"\n'
p.write_text(t)
PY
.dpcli/dpcli init >/dev/null
say "init done (agents, skills, process, CLAUDE.md block, permissions, update hook)"

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
