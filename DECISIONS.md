# Decisions

## ADR 6, security is fixed, not fled from

Status: accepted 08-29-2026

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

## ADR 5, the coordinator is the only writer of COMMS.md

Status: accepted 08-29-2026

Context. Two proposed architectures had the agents read and write `COMMS.md` directly, using it as
the message bus between them.

Decision. Agents never write to it. `orchestrator.py` takes each agent's standard output and writes
it into the round unchanged.

Consequences. The record cannot be edited by a participant mid-run, and no model sits between what
codex said and what the file holds, so nothing can be quietly paraphrased. This was the third
finding in the first review ever run through the loop, and it is in `COMMS.md`.

## ADR 4, questions stop the run and answers go back in through the file

Status: accepted 08-29-2026

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

## ADR 3, improvements do not hold a round open

Status: accepted 08-29-2026

Context. Every review finds something. Without a distinction, the loop runs until the round cap
every time and the cap becomes the only stopping rule.

Decision. The reviewer tags each finding `[SECURITY]`, `[BLOCKING]` or `[IMPROVEMENT]`. Only the
first two hold a round open. A review containing any untagged line is never shippable.

Consequences. The smallest thing that works is what gets selected, enforced by the coordinator
rather than left to an agent's discretion. The untagged rule costs something real: a reviewer that
wraps one finding across two lines keeps the round open, because a continuation line cannot be told
from an untagged finding. It fails towards another round, never towards shipping.

## ADR 2, the training log is a build product

Status: accepted 08-28-2026

Context. Amine wanted both a per-project record and one amalgamated file for training. Two writers
to two files drift, and the disagreement surfaces months later with neither side obviously right.

Decision. Each project's `routing.jsonl` is the record. `collect.py` reads them all and writes
`training.jsonl`. Nothing is ever authored there by hand.

Consequences. Skipping a collection costs nothing, because it rebuilds from the projects every time
and there is no moment that can be missed. Checking it is reading two counts that the script prints,
not reading the file.

Rejected: a dump at the end of each session. It only happens if the session reaches its end, and a
missing line looks exactly like work that was never done.

## ADR 1, there is no unlogged mode

Status: accepted 08-28-2026

Context. `--task-id` started optional. Without it the coordinator ran and recorded nothing.

Decision. It is required. A run with no writer is refused rather than run unlogged.

Consequences. Every round through the coordinator is on the record. Codex raised this as blocking:
an optional switch makes the exact gap the log exists to close reachable by leaving out a flag.

## Notes

The decision event is never written by the coordinator. It prints the three commands with the ids
filled in and stops, because the judgment is Amine's. One judgment fills all three lines: the review
carries the real verdict on the findings, the other two carry whether the work moved on.

`findings` is counted only from the severity tags. Counting bullets in prose writes numbers that
look measured and are not, which `ROUTING.md` refuses on purpose.

Open, and Amine's to decide. Claude always builds and codex always reviews, so `participant` never
varies and a routing model has no label to learn from. The fix is alternating who builds, per task
rather than per round.
