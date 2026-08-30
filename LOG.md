# Log

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
