# Routing log

The record of every dispatch: what was known before the work was sent, what came back, and what was
decided about it. This is the file that makes a learned router possible later, and it only exists if
it is written as the work happens. None of it can be reconstructed afterwards.

`routing.jsonl` holds it. One JSON object per line, appended, never edited.

## Three events, not one

The first version of this file was wrong in a way worth recording. It kept one line per dispatch
holding both what was known beforehand and what happened after, and claimed the early fields were
the router's input. They are not. How long a call took, how many findings came back and how many
rounds a task eventually needed are all unknowable at the moment the routing decision is made. A
model trained on them learns from information it will not have.

So the record is split by when the information exists.

### dispatch

Written immediately before the work is sent. Every field here is available at decision time, which
is what makes them usable as features.

    event           "dispatch"
    id              unique, generated here. Nothing else identifies a dispatch: one round
                    contains a proposal, a review and a disposition
    task_id         stable across every round of one task. Without it the dispatches that
                    make up a stopping sequence cannot be found again
    round           integer, matching the round in COMMS.md
    seq             position within the round, from 1
    parent          id of the dispatch this responds to, null for the first in a round
    started         ISO 8601, from the clock, never typed
    task            the exact request that was sent, not a summary of it
    kind            build | review | fix | research | scaffold
    role            builder | reviewer
    available       every participant that could have taken this, as a list
    participant     the one that did
    model           the model behind it, if known
    open_findings   how many findings from earlier rounds are still unresolved
    rounds_so_far   how many rounds this task has already taken
    elapsed_so_far  seconds spent on this task before now

The last three are the state the stopping decision is made against. Without them a router can see
that you stopped but not what you were looking at when you did.

### result

Written when the dispatch ends, in every path: success, failure, timeout, interruption. A dispatch
that dies without a result line is worse than one never logged, because the gap looks like data.

    event           "result"
    id              the dispatch it belongs to
    ended           ISO 8601
    seconds         wall clock
    status          ok | failed | timeout | interrupted
    error           what went wrong, required unless status is ok
    findings        integer, only when the reply was a structured list and the count is
                    real. Null otherwise. Do not infer it by counting bullets
    tokens          when the tool reports it, else null

### decision

Written when a person or the builder disposes of the result. This carries the labels.

    event           "decision"
    id              the dispatch it belongs to
    at              ISO 8601
    stop            stop | continue. Whether the task was done
    adoption        adopted | refused | partial | none. What happened to the work
    rev             0 for the first decision on a dispatch, incremented for each
                    correction. The highest rev wins, which stays unambiguous when two
                    decisions land in the same second
    reason          why. Required for refused and partial, and for every correction
    by              human | builder. Who decided

`stop` is the field the whole log exists for. It is the expensive judgment, the one made constantly
and articulated never, and nothing else in the record captures it.

`reason` is the field that will feel pointless and matters most. A refusal without one teaches a
router what gets rejected but not what makes something rejectable.

A decision that turns out wrong is corrected by appending another decision with the same `id`. The
later one wins. Nothing is ever edited, so `human accepted` is never quietly rewritten into
something flattering.

## What is a feature and what is a label

Everything in the `dispatch` line is known before the work is sent, and everything in `result` is
known only after. That is the line between what a router can be given and what it must predict.

There are two different models in here and they do not share a feature set.

For the **stopping** model, the question is whether this task is done. Features are the whole
dispatch line including `participant`, since you know who did the work when you judge whether to
stop. The label is `stop`.

For the **routing** model, the question is who should get this. `participant` is the label, not a
feature, and `available` is the set it was chosen from. Training on `participant` as an input teaches
a model to predict the choice from the choice.

`adoption` is a second label, useful for both.

`rounds_so_far` is a feature. A total round count for the finished task is not, and does not appear
here for that reason.

## Honest gaps

`findings` is not reliably countable from free prose. It is null unless the reviewer returned
something structured, and a router should not lean on it.

`by: builder` decisions are weaker labels than `by: human` ones. Keep the field so the difference
stays visible rather than averaging the two together.

Nothing here is worth training on until there are a few hundred dispatches across varied work. Until
then it is read by hand, and reading it is how the fields get corrected. Note any change here with
the date.

## Writing it

`routelog.py`, next to this file, appends the three event types and generates ids. It is the only
supported writer, and it refuses what would make the log untrainable: a dispatch whose participant
was not among those available, a result on a dispatch that already ended, a decision on a dispatch
with no result, a correction with no reason, negative counts, and non-finite numbers that would
write `NaN` into JSON that is meant to be standard.

    id=$(python3 routelog.py dispatch --task-id signup-form --round 3 --seq 1          --task "<the exact request>" --kind review --role reviewer          --available "claude,codex" --participant codex)
    python3 routelog.py result --id $id --seconds 61 --status ok --tokens 14379
    python3 routelog.py decision --id $id --stop continue --adoption adopted --by human

`orchestrator.py` calls it, as of 08-28-2026. Every round records three dispatches and a result for each,
on every path out including timeout and interruption. `--task-id` is required and there is no
unlogged mode, since a run that leaves no record is the gap this exists to prevent.

The coordinator does not write `decision` events. That judgment is the human's, so it prints the
three commands with the ids filled in and stops. One judgment fills all three: the review carries
the real verdict on the findings, the other two carry whether the work moved on.

`tokens` is filled when the agent's command reports it. Each tool prints usage its own way, so the
command writes the number to a `{tokens}` path the coordinator provides and the coordinator parses
nothing. A turn that reports nothing is recorded as null, never as zero.

## The training log

`training.jsonl`, beside `collect.py`, is every project's `routing.jsonl` read together,
each record stamped with the `project` it came from. `collect.py` writes it.

It is a build product and nothing is ever authored there by hand. It is rebuilt from the project
logs every run, so skipping a run costs nothing and there is no moment that can be missed. If it is
ever wrong, delete it and run `collect.py` again.

Dispatch ids are generated per project, so the pair of `project` and `id` is what identifies a
dispatch once the projects are read together.

The reason for it is that a project on its own cannot teach routing. Inside one project the roles
are fixed on day one, so `participant` barely varies and there is nothing to learn from. The
variation lives across projects, which is the only place it can be seen.

`collect.py` prints what it found per project, including how many dispatches have no result and how
many are still waiting on a decision. Those counts are the check: nobody has to read the file.
