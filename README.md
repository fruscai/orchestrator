# Orchestrator

Runs build, read-only review and disposition rounds between two command-line agents, and writes
down every exchange. One agent builds, the other attacks what it built, and the argument is the
record.

`Claude_Projects` holds this repository and every project made from it. It is a folder, not a
repository of its own.

- `orchestrator.py` runs the rounds
- `routelog.py` writes the dispatch log, and is the only supported writer
- `collect.py` reads every project's log into `training.jsonl`
- `report.py` says in sentences what that log holds
- `answer.py` puts your answers to an agent's questions back into `COMMS.md`
- `newproject.command` makes a new project set up for the loop
- `ROUTING.md` describes the dispatch log and why each field is in it
- `codex-project-prompt.md` is the block to paste when starting from the Codex side instead

The commands are trusted local programs. They inherit the current environment and filesystem
permissions. The coordinator controls round count, per-turn time and communication order. It does
not isolate untrusted programs.

## Starting a project

1. Double-click `newproject.command`. A Terminal window opens. No security warning, the file was
   written locally.
2. Type a name and press return. Letters, numbers, dot, dash and underscore only. It refuses
   anything else rather than making a nested folder.
3. Press return again to put it in `Claude_Projects`, or type a different path first.
4. Read what it printed, then press return to close the window.
5. Start a session in the new folder and open with:

       New project: <what it is, a sentence or two>. Run the two-agent loop from memory.
       Write the brief first and show it to me before building anything.

6. Correct the brief, or approve it. Nothing gets built until you do.
7. Say "run a round" when you want the work attacked.

### What the script made

    BRIEF.md      the task and the two roles, blanks for you to fill
    COMMS.md      every exchange, oldest first
    ROUTING.md    what the dispatch log holds and why
    routelog.py   writes it. The log appears on first use, not before
    proposals/    patches from the reviewer, applied or refused
    .gitignore    project noise only, nothing that names a tool

On a branch called `work`, so you never start on `main`. Nothing is committed. Both ignore layers
are in place, which you can confirm with `git check-ignore -v CLAUDE.md`.

## Running a round

```sh
python3 ~/Desktop/Claude_Projects/orchestrator/orchestrator.py "what to do" \
  --agent-a '<builder command>' \
  --agent-b '<read-only reviewer command>' \
  --builder a \
  --review-areas 'correctness, failure handling and tests' \
  --round-title 'short title for what this round is about' \
  --rounds 1 \
  --task-id 'the-task-being-routed' \
  --workdir .
```

Each completed round is appended to `COMMS.md` with a clock-generated date and time. The entry
holds the exact review prompt, the unedited reviewer reply and the builder's disposition. Dates and
rounds stay oldest first, and round numbers continue across separate runs.

The builder side, review areas, a task id and at least one round title are required. Choose the
builder side before the first round. Rounds is a ceiling, not a count: a review that replies with
exactly `NO FINDINGS` ends the run early, and the last title supplied covers any round past the
titles given.

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
python3 ../orchestrator/answer.py --comms COMMS.md "yes, an empty file is an error"
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
finding still open at the last review, 5 waiting on an answer, 130 interrupted.

## The routing log

Every dispatch is recorded through `routelog.py` into `routing.jsonl`, with a result on every exit
path. A run without a reachable `routelog.py` is refused; there is no unlogged mode.

`orchestrator.py` writes the dispatch and result lines itself and prints the decision commands for
you, because the decision is yours:

    python3 routelog.py decision --id <id> --stop continue --adoption adopted --by human

`ROUTING.md` explains why the record is split into three events and which fields a router can be
trained on.

Run `python3 collect.py` whenever you want the projects gathered into `training.jsonl`, and
`python3 report.py` to read what it holds in sentences.

## Closing a session

End the session when the piece of work is done, especially when there is an obvious next step.
Start the next piece in a fresh one.

The reason is cost. A conversation is re-read in full on every turn, so a thread that runs twice as
long costs roughly four times as much across its life. Nothing can be compressed away after the
fact. The only lever is stopping.

Before stopping, write the handoff: `COMMS.md` for the argument, `LOG.md` for what happened,
`DECISIONS.md` for why. The test is whether a fresh session can pick the work up from those files
without being told anything. If it cannot, something that mattered lived only in the conversation,
and that is the gap to fix in the files rather than a reason to keep the thread open.

## Two things that will bite you

Memory is scoped per folder. A new project starts with none of it, which is why the script copies it
across. That copy is a snapshot, not a link: anything learned inside a project stays there and has
to be copied back by hand to reach anywhere else.

The routing log is only useful if it is written every time, including when a dispatch fails. A gap
looks like data, and it cannot be reconstructed later.

## Test

```sh
python3 -m unittest discover -s tests -v
```
