# Log

## 08-30-2026

One repository

`Claude_Projects` is a container for repositories and holds nothing else. `duel-coordinator` was
renamed `orchestrator` and everything loose at the root moved into it: `routelog.py`, `collect.py`,
`report.py`, `answer.py`, `newproject.command`, `ROUTING.md`, `codex-project-prompt.md` and both
logs. The rename kept the five existing commits.

A repository was created at the root first, then removed. It had not been committed, so nothing was
lost.

Renumbered by date

Two folders each kept their own records, so the merge arrived with two of everything. `COMMS.md` is
5 consecutive rounds, the root's 08-29 09:39 round landing as Round 4 ahead of the coordinator's
09:51 one. `DECISIONS.md` is 11 ADRs: the root's five kept 1 to 5, the coordinator's six became 6 to
11, each carrying a line naming its old number. The two routing logs concatenated to 18 records with
no id collisions.

Tests that pass without running

- ⚠️ the tests locate `routelog.py` and `answer.py` by path. Moving them left every path wrong, and
  the suite printed `OK (skipped=33)`. Not one assertion ran. Lesson: read the skip count, not the
  OK
- `collect.py` scanned its own folder for projects. The projects now sit beside it, so the default
  root is the parent
- verified after the fix: 33 tests in 13 seconds, `collect.py` reads 18 records across 3 tasks,
  `report.py` prints, `newproject.command` passes `zsh -n`

## 08-29-2026

Renamed

`duel.py` is now `orchestrator.py`, and the test file with it. `COMMS.md` and `routing.jsonl` were
left alone: they record what was actually sent and said at the time, and rewriting a record to match
a later name makes it a worse record.

Severity rules and the smallest working thing

The reviewer now starts every finding with `[SECURITY]`, `[BLOCKING]` or `[IMPROVEMENT]`. Only
security and blocking hold a round open, so the loop stops at the smallest thing that works rather
than at the point nobody can think of another improvement.

A review with any untagged line is never shippable. The first version only checked that no
recognised tag said blocking, which meant one readable `[IMPROVEMENT]` laundered an untagged
finding sitting beside it. Ten tests failed on that version, and codex found the remaining hole in
review.

The tags also gave `routelog` a real `findings` count. It had been null on every record ever
written, because nothing could count prose honestly. It is still null when the reviewer does not use
the tags.

Security no longer condemns a run it did not end in

A security finding used to force exit 4 even when a later round fixed it and the reviewer came back
clean. Now exit 4 means still open at the last review. Raised and then fixed exits 0 with a line
saying so, because the fix was the builder's claim and a quiet later review is not the same as
having looked.

Questions and answers

Any agent can put `[QUESTION]` on its own line. Those are collected from all three turns, written
into the round in `COMMS.md` under `questions for you`, and the run stops. Answers go in through
`answer.py` as their own `answers to round N` block, appended rather than written over the
questions. `Passthrough` records a question that was put and left unanswered on purpose. The
coordinator reads the last answers block back out of `COMMS.md` and puts it in the next round's
build prompt, so nothing is retyped by hand.

Found while building it: a round that shipped with an improvement still open was writing "The
reviewer reported no findings" into `COMMS.md`, which was false.

## 08-28-2026

The coordinator writes the routing log

`orchestrator.py` records three dispatches a round through `routelog.py`, called as a subprocess because
routelog exits the process on every validation failure. The result is written on every path out,
including timeout and interruption. `--task-id` is required and there is no unlogged mode.

`run_agent` raises an `AgentError` carrying a status, so the log never depends on matching the
wording of an error message.

Codex found two holes in the first version. Logging was optional, which made the gap it exists to
close reachable by leaving out a flag. And a Ctrl-C landing between writing the dispatch record and
entering the block that answers it exited with no result line. SIGINT is now held across that
window.

Rounds became a ceiling

`--rounds` defaults to 3 and stops early when the reviewer reports nothing. Because a run can stop
early, one title per round is no longer required. The build prompt carries only the last
disposition; it used to join every prior one, so round three re-sent rounds one and two in full.

Exit codes: 0 done, 1 error, 2 usage, 3 rounds used up with blocking findings open, 4 security still
open, 5 waiting on an answer, 130 interrupted.

Token capture

A `{tokens}` placeholder alongside `{prompt}` and `{output}`. The agent's command writes its number
there and the coordinator parses nothing, so no tool's output format is baked in. A turn that
reports nothing is recorded as null, never as zero. Verified against codex, which prints its usage
on stderr.

The collector

`collect.py` reads every project's `routing.jsonl` into `training.jsonl`, stamping each record with
its project. It prints what it found per project, including dispatches with no result and dispatches
with no decision. Those counts are the check, so nobody has to read the file. It missed the root's
own log at first, which would have meant work on the shared scripts was written and never collected.

`report.py` reads the training log and says in sentences what it holds. Codex found five defects in
it, all verified by running them: equal revisions resolved to the earlier record, a null revision
crashed, an unknown adoption printed as `kept 0`, a participant with no timings vanished from the
cost section along with their token total, and the confound warning fired wrongly with three or more
participants.

setup

- `Claude_Projects` created on the Desktop, everything moved out of Downloads
- holds `newproject.command`, `duel-coordinator`, `duel-landing`, `routelog.py`, `ROUTING.md`,
  `README.md`, `codex-project-prompt.md`
- `codex-project-prompt.md` was not in Downloads when the move ran. Rewritten from context, not
  recovered. `~/.Trash` is not readable from the CLI so it was not checked

first loop, duel-landing

- three rounds between Claude and codex on a one-file landing page, codex read-only
- round 1: no `<label>` on the email input, form posting to a `/signup` that does not exist
- round 2: the confirmation claimed a signup that never happened, and `method="get"` was writing the
  address into the URL and history. Dropped `name` off the input so nothing is submitted
- round 3: codex found the timestamps on rounds 0 and 1 were invented. 15:40 and 16:05, neither
  measured. Replaced with 12:11 and 12:18 off the filesystem
- ⚠️ `codex exec` HANGS forever reading stdin when stdin is not a terminal. Prints "Reading
  additional input from stdin..." and nothing else. Needs `</dev/null`. Cost one 300 second timeout
  before it was spotted
- `:focus-visible` does NOT match focus arriving through a fragment on a `tabindex="-1"` element.
  Confirmed in the browser. Used plain `:focus`
- the focus ring itself is not verified. The preview pane never holds window focus, so
  `document.hasFocus()` is false and `:focus` cannot match there

newproject.command

- double-clickable zsh script, three rounds with codex
- round 1, eleven findings. `set -e` plus `read` meant every "press return to close" was skipped on
  EOF, so a failed double-click would have closed the window before anything could be read
- round 2, three findings. `eval` had been used to expand the typed path, so typing `$(command)` as
  the destination would have run it. Removed
- round 3, four findings. Refusing `$` and backticks was pointless once `eval` was gone
- two race findings refused. Both need another process racing a double-clicked script on the same
  machine
- removed the `open` call at the end. It was firing a Finder window on every run including tests

memory scoping

- BIG ONE: **memory is scoped per working directory.** A session started in a new folder gets an
  empty memory, not the one from home
- `~/.claude/projects/-<home>/memory` and
  `~/.claude/projects/-<home>-Desktop-Claude_Projects/memory` are separate directories
- `newproject.command` copies the files across. It is a snapshot, not a link

duel-coordinator

- already existed in Downloads, built in an earlier thread. `duel.py`, 286 lines,
  `tests/test_duel.py`, 218 lines, seven tests, all pass
- drives two arbitrary command-line agents through build, review and disposition rounds and writes
  `COMMS.md` itself
- `round.sh` in `duel-landing` is a narrower duplicate. No longer copied into new projects

routing log

- two rounds with codex, both against the design rather than code
- round 1: the first spec leaked labels. Duration, finding count and rounds-to-converge are all
  unknown at the moment the routing decision is made. It also had no stop label, and `round` could
  not identify a dispatch when one round contains three
- rebuilt as three events, `dispatch`, `result`, `decision`, split by when the information exists
- round 2: no `task_id` linking dispatches across rounds, two corrections in the same second were
  ambiguous, `os.write` can short-write and the return value was ignored, `NaN` would have been
  written into the JSON, and `participant` is a label for the routing model rather than a feature
- `routelog.py` written. Refuses a participant that was not offered, a second result on one
  dispatch, a decision before a result, a correction with no reason, negative counts, non-finite
  numbers
- `duel.py` does NOT call it yet. Coordinator rounds land in `COMMS.md` and not in the routing log

cost

- measured from the session transcript: 195,321 output, 632,299 cache write, 28,024,821 cache read,
  506 fresh input
- codex reported 6,436, 13,543, 25,528, 10,298 and 14,379 across the rounds that were captured
- the cache read is the conversation being re-read every turn. It grows with thread length and
  nothing compresses it after the fact. Lesson: close the session when the work is done
