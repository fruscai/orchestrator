#!/bin/zsh
# Double-click to start a project set up for the two-agent loop.
# Asks for a name, creates the folder, seeds the ignore layer, copies the round
# harness, and carries the memory across so the new session already knows the rules.

set -e
setopt no_nomatch          # an empty glob must not abort the script
cd "$(dirname -- "$0")"

MEMROOT=~/.claude/projects
SOURCE_MEM=$MEMROOT/-<home>/memory
COORD=~/Desktop/Claude_Projects/orchestrator/orchestrator.py
SPEC=~/Desktop/Claude_Projects/orchestrator/ROUTING.md
WRITER=~/Desktop/Claude_Projects/orchestrator/routelog.py
PARENT=~/Desktop/Claude_Projects

made=""
made_id=""
mem_target=""
mem_seeded=""
pause() { read "?Press return to close." 2>/dev/null || true }
bail() { print; print "$1"; pause; exit 1 }

# If anything fails after the folder exists, take it back out rather than leaving
# a half-built project that the next run will refuse to touch.
cleanup() {
  local code=$?
  [[ $code -eq 0 ]] && return
  # Only remove the directory if it is still the same one this run created.
  # Comparing device and inode means a replaced path is left alone.
  if [[ -n "$made" && -d "$made" ]]; then
    local now=$(stat -f '%d:%i' -- "$made" 2>/dev/null || true)
    if [[ -n "$made_id" && "$now" == "$made_id" ]]; then
      print
      print "Failed partway. Removing $made so you can run this again."
      rm -rf -- "$made"
    else
      print
      print "Failed partway. Left $made alone, it is no longer the directory this run made."
    fi
  fi
  # A half-copied memory directory is worse than none, but only clear one this run seeded.
  if [[ -n "$mem_seeded" && -d "$mem_target" ]]; then
    print "Removing the partly copied memory at $mem_target."
    rm -rf -- "$mem_target"
    rmdir -- "${mem_target:h}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

print
print "New project"
print "-----------"
print
read "name?Name (letters, numbers, dot, dash, underscore): " 2>/dev/null || bail "No input. Nothing done."
[[ -z "$name" ]] && bail "No name given. Nothing done."
if [[ ! "$name" =~ '^[A-Za-z0-9._-]+$' || "$name" == .* ]]; then
  bail "\"$name\" is not a plain name. No slashes, spaces, newlines or leading dots."
fi

read "where?Where to put it [$PARENT]: " 2>/dev/null || where=""
if [[ -n "$where" ]]; then
  # Expand a leading tilde by hand. Nothing here is evaluated, so a path holding
  # $ or a backtick is just a path and passes through untouched.
  where=${where/#\~\//$HOME/}
  [[ "$where" == "~" ]] && where=$HOME
  PARENT=$where
fi

mkdir -p -- "$PARENT" || bail "Cannot create $PARENT."
PARENT=${PARENT:A}                          # resolve symlinks, .. and trailing slashes
dir=$PARENT/$name

# mkdir without -p is atomic: it fails if the directory already exists, so there is
# no gap between checking and creating in which something else could appear.
if ! mkdir -- "$dir" 2>/dev/null; then
  [[ -e "$dir" ]] && bail "$dir already exists. Nothing done."
  bail "Could not create $dir."
fi
made=$dir
made_id=$(stat -f '%d:%i' -- "$dir")
cd -- "$dir"

git init -q
git checkout -q -b work

# Ignore layers. The tracked file gets project noise only. Everything that would
# name an editor goes in .git/info/exclude, which never gets committed.
cat > .gitignore <<'EOF'
node_modules/
dist/
build/
.venv/
__pycache__/
*.pyc
.DS_Store
.env
.env.*
!.env.example

# the round transcript, names the agents by tool name and never goes into a repository
COMMS.md
EOF

if [[ -f ~/.gitignore_global ]]; then
  cat ~/.gitignore_global >> .git/info/exclude
else
  print "No ~/.gitignore_global found. Skipped the exclude layer, set it up by hand."
fi

if [[ ! -f "$COORD" ]]; then
  print "No coordinator at $COORD. Rounds will need it before they can run."
fi

mkdir -p proposals

cat > COMMS.md <<EOF
# Comms

Every exchange between agents on this project. Dated \`## MM-DD-YYYY\`, oldest first, and oldest
round first inside each date, because this is a thread and it only makes sense read forward.
Rounds are numbered and never renumbered.

Each round holds the exact prompt that was sent, the reply verbatim, and what changed because of it.
A round that asked something also holds \`questions for you\`, and the answers appended under
\`answers to round N\`. \`Passthrough\` means it was left unanswered on purpose.
Changes arrive as patches in \`proposals/\`, never as direct edits. A refused patch is recorded with
its reason.

EOF

# The log file itself is not created here. An empty routing.jsonl with nothing
# writing to it reads as a record that exists, when nothing has been recorded.
if [[ -f "$SPEC" && -f "$WRITER" ]]; then
  cp -- "$SPEC" ROUTING.md
  cp -- "$WRITER" routelog.py
else
  print "No routing spec or writer found. This project will keep no dispatch record."
fi

cat > BRIEF.md <<EOF
# Brief

$name

Constraints:
-

Roles:
- Claude builds
- Codex reviews adversarially, read-only, and cannot edit the files under review

One writer per path per round. Every round is logged in \`COMMS.md\`. Every dispatch is recorded
through \`routelog.py\`, which \`ROUTING.md\` explains. The coordinator does not call it yet, so
those lines are written by hand.
EOF

# Memory is scoped per working directory, so a new folder starts with none of it.
# The key comes from the resolved path, since that is what a session there will use.
target=$MEMROOT/${${dir:A}//\//-}/memory
mem_target=$target
[[ -d "$target" ]] || mem_seeded=1        # only clean up one this run created
mkdir -p -- "$target"

files=("$SOURCE_MEM"/*.md(N))
if (( ${#files} == 0 )); then
  print "No memory files at $SOURCE_MEM. The new session will start blank."
else
  existing=("$target"/*.md(N))
  if (( ${#existing} > 0 )); then
    print
    print "$target already holds ${#existing} memory files."
    read "ans?Overwrite the ones with matching names? [y/N] " 2>/dev/null || ans=n
    if [[ "$ans" != [yY]* ]]; then
      made=""       # the project itself is fine, only the memory copy was declined
      mem_seeded="" # and the existing memory directory is not ours to remove
      bail "Left the existing memory alone. $dir was still made, without memory."
    fi
  fi
  # Copy into a staging directory first, then move the files into place. A copy that
  # fails partway leaves the existing memory as it was rather than half replaced.
  stage=$target/.staging-$$
  mkdir -p -- "$stage"
  if ! cp -- "${files[@]}" "$stage"/; then
    rm -rf -- "$stage"
    bail "Could not copy the memory files. Left $target as it was."
  fi
  mv -f -- "$stage"/*.md "$target"/
  rmdir -- "$stage"
  print "Carried ${#files} memory files across."
fi

made=""        # past the point where a failure should undo the project
mem_seeded=""

print
print "Made $dir on branch work."
print "Nothing committed. Nothing opened. Start a session there with:"
print
print "  New project: <what it is>. Run the two-agent loop from memory. Write the brief"
print "  first and show it to me before building anything."
print

pause
