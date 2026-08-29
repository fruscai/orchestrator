# Duel coordinator

Runs build, read-only review and builder-disposition rounds between two command-line agents.

The commands are trusted local programs. They inherit the current environment and filesystem
permissions. The coordinator controls round count, per-turn time and communication order. It does
not isolate untrusted programs.

Each completed round is appended to `COMMS.md` with a clock-generated date and time. The entry
contains the exact review prompt, the unedited reviewer reply and the builder's disposition. Dates
and rounds stay oldest first. Round numbers continue across separate runs.

The builder side, review areas, a task id and at least one round title are required. Choose the
builder side with the user before the first round. Rounds is a ceiling, not a count: a review that
replies with exactly `NO FINDINGS` ends the run early, and the last title supplied covers any round
past the titles given. Every dispatch is recorded through `routelog.py` into `routing.jsonl`, with
a result on every exit path. A run without a reachable `routelog.py` is refused; there is no
unlogged mode.

## Run

```sh
python3 duel.py "Implement the requested change" \
  --agent-a '<builder command>' \
  --agent-b '<read-only reviewer command>' \
  --builder a \
  --review-areas 'correctness, failure handling and tests' \
  --round-title 'the first implementation and its failure paths' \
  --rounds 1 \
  --task-id 'the-task-being-routed' \
  --workdir /path/to/project
```

Commands normally receive their prompt through standard input. A command containing `{prompt}`
receives the prompt as an argument and gets `/dev/null` as standard input. A command containing
`{output}` must write its final response to that path. Both placeholders can be used together.

Timeout and interruption terminate the active agent process group. A descendant that creates a
separate process group is outside that boundary, but it cannot keep the coordinator waiting on the
original output pipes.

## Questions

Any agent can put a line starting with `[QUESTION]` in its reply. Those lines are collected from all
three turns, written into the round in `COMMS.md` under `questions for you`, printed, and the run
stops with exit 5. A question that does not stop the run is not a question: the rounds after it
would rest on an answer nobody gave.

Answer before the next round:

```sh
python3 ../answer.py --comms COMMS.md "yes, an empty file is an error"
```

The answers are appended as their own block, `answers to round N`, so what was asked stays exactly
as it was asked. Every question gets a line. `--passthrough` fills the rest with `Passthrough`,
which records that a question was put and left unanswered on purpose. That is not the same as never
having been asked, and the next round is told the difference.

The coordinator reads the last answers block out of `COMMS.md` itself and puts it in the next
round's build prompt. Nothing is retyped by hand.

## Findings and severity

The reviewer starts every finding with `[SECURITY]`, `[BLOCKING]` or `[IMPROVEMENT]`. Improvements
do not hold a round open, so the loop stops at the smallest thing that works. A review with any
untagged line is never shippable: a reviewer ignoring the format has said nothing that can be read,
and ambiguity holds the round open rather than shipping.

Exit codes: 0 done, 1 error, 2 usage, 3 rounds used up with blocking findings open, 4 a security
finding was raised, 5 waiting on an answer, 130 interrupted.

## Test

```sh
python3 -m unittest discover -s tests -v
```
