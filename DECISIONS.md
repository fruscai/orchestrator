# Decisions

## ADR 12, no personal or system information reaches a repository

Status: accepted 08-31-2026

Context. This repository was made public with `/Users/<name>` written into `LOG.md`, `COMMS.md` and
`newproject.command`, in the working tree and in every earlier commit. Making a repository private
again does not undo a public one: clones, forks and caches survive the change.

Decision. No absolute home path, username, IP address, hostname, key, token or email address goes
into any repository, public or private. Paths are derived rather than written out:
`$MEMROOT/${HOME//\//-}/memory` carries no username where the literal path does. Anything already
committed is removed from history rather than only from the tip.

Consequences. The security review pass carries this as a standing job, not a one-off check, and
a review that only reads the working tree is not enough. A history rewrite needs a force push, and
that is Amine's to run.

## ADR 11, security is fixed, not fled from

Status: accepted 08-29-2026
Was ADR 6 until 08-30-2026, when the projects root and the coordinator became one repository.

Context. A security finding used to condemn the whole run. Once raised, the run exited 4 even if the
next round fixed it and the reviewer came back clean.

Decision. Security behaves like a blocking finding: it holds the rounds open until it is gone. Exit
4 means still open at the last review. Raised and then fixed exits 0, with a line on stderr saying
it was raised earlier and to check it yourself.

Consequences. The loop can finish a task that had a security problem in it, which is the point. The
warning on a fixed one is deliberate: the fix was the builder's claim, and a later reviewer going
quiet is not the same as a person having looked.

Amine's reasoning, in his words: a security issue would not stop the process, it would have to be
fixed.

## ADR 10, the coordinator is the only writer of COMMS.md

Status: accepted 08-29-2026
Was ADR 5 until 08-30-2026, when the projects root and the coordinator became one repository.

Context. Two proposed architectures had the agents read and write `COMMS.md` directly, using it as
the message bus between them.

Decision. Agents never write to it. `orchestrator.py` takes each agent's standard output and writes
it into the round unchanged.

Consequences. The record cannot be edited by a participant mid-run, and no model sits between what
codex said and what the file holds, so nothing can be quietly paraphrased. This was the third
finding in the first review ever run through the loop, and it is in `COMMS.md`.

## ADR 9, questions stop the run and answers go back in through the file

Status: accepted 08-29-2026
Was ADR 4 until 08-30-2026, when the projects root and the coordinator became one repository.

Context. An agent that needs a human judgment had nowhere to put it. Questions were printed to a
terminal and otherwise buried in a transcript that could not even be grepped, because the review
prompt contains the tag and is recorded verbatim.

Decision. `[QUESTION]` lines are collected from all three turns, written into the round under
`questions for you`, and the run stops. Answers are appended as their own `answers to round N`
block through `answer.py`, never written over the questions. `Passthrough` records a question left
unanswered on purpose. The coordinator reads the last answers block out of `COMMS.md` itself and
puts it into the next round's build prompt.

Consequences. A question cannot be lost by closing a window, and the answer reaches the next round
without being retyped, which is the step that quietly stops happening. `Passthrough` exists because
an unanswered question is not the same as one never asked, and the next round is told which.

## ADR 8, improvements do not hold a round open

Status: accepted 08-29-2026
Was ADR 3 until 08-30-2026, when the projects root and the coordinator became one repository.

Context. Every review finds something. Without a distinction, the loop runs until the round cap
every time and the cap becomes the only stopping rule.

Decision. The reviewer tags each finding `[SECURITY]`, `[BLOCKING]` or `[IMPROVEMENT]`. Only the
first two hold a round open. A review containing any untagged line is never shippable.

Consequences. The smallest thing that works is what gets selected, enforced by the coordinator
rather than left to an agent's discretion. The untagged rule costs something real: a reviewer that
wraps one finding across two lines keeps the round open, because a continuation line cannot be told
from an untagged finding. It fails towards another round, never towards shipping.

## ADR 7, the training log is a build product

Status: accepted 08-28-2026
Was ADR 2 until 08-30-2026, when the projects root and the coordinator became one repository.

Context. Amine wanted both a per-project record and one amalgamated file for training. Two writers
to two files drift, and the disagreement surfaces months later with neither side obviously right.

Decision. Each project's `routing.jsonl` is the record. `collect.py` reads them all and writes
`training.jsonl`. Nothing is ever authored there by hand.

Consequences. Skipping a collection costs nothing, because it rebuilds from the projects every time
and there is no moment that can be missed. Checking it is reading two counts that the script prints,
not reading the file.

Rejected: a dump at the end of each session. It only happens if the session reaches its end, and a
missing line looks exactly like work that was never done.

## ADR 6, there is no unlogged mode

Status: accepted 08-28-2026
Was ADR 1 until 08-30-2026, when the projects root and the coordinator became one repository.

Context. `--task-id` started optional. Without it the coordinator ran and recorded nothing.

Decision. It is required. A run with no writer is refused rather than run unlogged.

Consequences. Every round through the coordinator is on the record. Codex raised this as blocking:
an optional switch makes the exact gap the log exists to close reachable by leaving out a flag.

## ADR 5, a session ends when the piece of work does

Status: accepted, 08-28-2026

Context. One session held the landing page, the starter script, the folder move and the routing log
design. Measured at the end: 28,024,821 cache-read tokens against 195,321 of output. A conversation
is re-read in full on every turn.

Decision. End the session when the piece of work is done, write `LOG.md`, `DECISIONS.md` and
`COMMS.md` first, and start the next piece fresh.

Consequences. More sessions, each cheaper. The files have to carry enough that a fresh session can
continue with nothing explained. When they cannot, the gap goes in a file rather than keeping the
thread alive.

Amine's framing, and it is the right one: those files exist so the conversation does not have to
hold the state.

## ADR 4, two models, two feature sets

Status: accepted, 08-28-2026

Context. Codex pointed out that `participant` is fine as an input when predicting whether to stop,
and is the answer itself when predicting who should get the work.

Decision. The stopping model takes the whole dispatch line including `participant` and predicts
`stop`. The routing model takes the dispatch line without `participant` and predicts it, from the
set in `available`.

Consequences. `available` has to be recorded even when there was only ever one real option, or the
routing model has no alternatives to learn from. `routelog.py` refuses a participant that was not in
that list.

## ADR 3, the routing log is three events, not one line

Status: accepted, 08-28-2026, replaces the first version written the same day

Context. The first spec kept one line per dispatch holding both what was known beforehand and what
happened after, and named the early fields as the router's input. Duration, finding count and
rounds-to-converge are not known when the routing decision is made.

Decision. `dispatch` before the work is sent, `result` when it ends, `decision` when it is disposed
of. Features are the dispatch line. Labels are `stop` and `adoption`.

Consequences. Three calls per dispatch instead of one. `duel.py` needs `run_agent` to return timing
and status, and all three dispatches per round logged in the success, failure, timeout and
interrupt paths. Until that is done the log is written by hand.

## ADR 2, the reviewer cannot edit

Status: accepted, 08-28-2026

Context. Codex runs `-s read-only` and cannot touch the files under review. Every finding has to be
written into `COMMS.md` and argued.

Decision. Keep the constraint. Changes from a reviewer arrive as unified diffs in `proposals/`,
checked with `git apply --check`, then applied or refused with the reason recorded.

Consequences. A finding costs more to act on. In round 2 of the landing page the reviewer said the
confirmation was claiming a signup that never happened. With write access that becomes a copy edit
and the reasoning is never seen.

Refusals are the half that git history cannot reconstruct.

## ADR 1, COMMS.md runs oldest first

Status: accepted, 08-28-2026

Context. `LOG.md` is newest first. The first `COMMS.md` copied that, so rounds ran 3, 2, 1, 0 down
the page while each round ran forwards inside itself. Reading the whole thread meant scrolling to
the bottom and reading up, then reading each round down.

Decision. Dates and rounds both run oldest first in `COMMS.md`. `LOG.md` keeps newest first.

Consequences. The two files no longer share an order, which has to be stated in each header.
`round.sh` and any future writer appends rather than prepends.

Amine caught this: "to read it in order, I need to read from bottom up yes?" A log is opened to see
the latest entry and stopped. A comms file is a thread, and round 3 is unreadable before round 2.

## Notes

The decision event is never written by the coordinator. It prints the three commands with the ids
filled in and stops, because the judgment is Amine's. One judgment fills all three lines: the review
carries the real verdict on the findings, the other two carry whether the work moved on.

`findings` is counted only from the severity tags. Counting bullets in prose writes numbers that
look measured and are not, which `ROUTING.md` refuses on purpose.

Open, and Amine's to decide. Claude always builds and codex always reviews, so `participant` never
varies and a routing model has no label to learn from. The fix is alternating who builds, per task
rather than per round.

## Not decided

Whether the AMD Halo gets bought, and whether a router is trained at all. Both were discussed on
08-28-2026 and neither was settled. The position reached was that the log has to exist first,
because a router trained on anything other than decisions Amine actually made is worth nothing, and
those decisions are unrecoverable if not written down as they happen.
