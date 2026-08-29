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

## Test

```sh
python3 -m unittest discover -s tests -v
```
