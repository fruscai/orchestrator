# Project setup prompt

Paste this as the first message when starting a project in Codex. It sets the working rules before
any code exists, which is the only time they are cheap to set.

---

Before writing any code, set up the project the way I work. Do these in order and tell me when each
is done.

## 1. Read my lexicon first

Look for `~/.claude/LEXICON.md`. If it exists, read it before writing a single word of prose,
including commit messages, comments, README text and anything in a `.md`. It holds my sentences,
what each one demonstrates, and the anti-patterns already caught in my projects.

If it does not exist, tell me, and ask me for three or four samples of my writing before you draft
anything I will put my name on. Do not guess at my voice from this prompt.

The lexicon never enters a repo, in any location, `docs/` included. It is machine-local.

## 2. Two ignore layers, neither committed

A repo's tracked `.gitignore` gets project noise only:

```gitignore
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
```

Nothing that names an assistant or an editor goes in it. That file is committed, so it would publish
which tools I use. Those rules live in two uncommitted layers instead:

- `~/.gitignore_global`, set as `core.excludesfile`, covering every repo on this machine
- `.git/info/exclude` inside each repo, which lives inside `.git/` and never travels

Both hold the same block. Append it to `.git/info/exclude` before the first commit, and again on
every fresh clone, since it does not travel with the repo:

```gitignore
CLAUDE.md
CLAUDE.local.md
COMMANDS.md
LEXICON.md
docs/LEXICON.md
AGENTS.md
GEMINI.md
.claude/
.claude.json
.cursor/
.cursorrules
.cursorignore
.aider*
.continue/
.windsurf/
.windsurfrules
.github/copilot-instructions.md
.specstory/
.ai/
.codeium/
.sourcegraph/
*.prompt.md
prompts/
```

Confirm it took:

```bash
git check-ignore -v CLAUDE.md
```

## 3. No tool names, no machine authors

No tool or model name appears anywhere in the repo. Not in commit messages, file names,
documentation, code comments or pull request text. Say "the editor" if you have to refer to one at
all. Contributor guidance goes in `CONTRIBUTING.md`, never in a file named after a product.

No `Co-Authored-By` trailer, no "Generated with", no attribution of any kind, unless I ask for it.
The reason is ownership, not vanity: US Copyright Office guidance (88 Fed. Reg. 16190) holds that an
AI tool is not an author, and git treats `Co-Authored-By` as a real contributor. I may sell, license
or port this work.

## 4. Commits

Subject line only. No body unless I ask. One line, starting with the date, then plainly what was
done, joined with commas and "and". Lower case after the date. No title case, no colon splitting a
subject from a description, no semicolons.

    July 16, worked through exercises 1 through 4 in arrays and completed all housekeeping
    August 13, gitignored commands.md and updated decisions

Never commit to `main` or `master`. Never force push without asking. Commit and push only when I ask.

## 5. The three documents

`LOG.md` is dated `## MM-DD-YYYY`, newest first, with plain phrases as section headers rather than
`###`. You open it to see what happened last, so the newest entry sits on top.

`DECISIONS.md` holds reasoning. Architecture decision records go at the top in ADR notation with
Status, Context, Decision and Consequences, with narrative notes underneath. Never write a decision
I did not actually make, and never quote an entry back to me as justification without first checking
who wrote it.

`COMMS.md` holds every exchange between you and any other agent on the project. Same date headings
as `LOG.md`, but **oldest first**, and oldest round first inside each date, because a comms file is
a thread and round 3 makes no sense before round 2. Rounds are numbered and never renumbered.

Each round looks like this:

    ## 08-28-2026

    Round 1 — the dead endpoint and the missing label
    12:18

    <Agent A> to <Agent B>

        the exact prompt that was sent, verbatim, in a fenced block

    <Agent B> to <Agent A>

    the reply, verbatim, unedited, including the parts that were wrong

    <Agent A> to itself

    what actually changed because of it, and what was left standing and why

When a round asks something, two more sections follow it:

    questions for you

    1. the question, exactly as the agent put it

    answers to round N

    1. the answer, or Passthrough

Questions are numbered and the answers are appended as their own block, never written back over the
questions. `Passthrough` means the question was put and left unanswered on purpose, which is not the
same as never having been asked. A round that asks something stops there, and the answers are
recorded before the next round runs.

Timestamps come from the clock in whatever script drives the loop, never typed by hand. Invented
timestamps read as plausible and are wrong, which is worse than no timestamp at all.

## 6. Running the adversarial loop

One agent builds. The other reviews read-only and cannot edit the files under review, so every
finding has to survive being written down and argued rather than quietly patched. Ask me which side
you are on before the first round.

When the reviewer is Codex driven from a script, the call is:

```bash
codex exec -C "$dir" --skip-git-repo-check -s read-only -o "$out" "$prompt" </dev/null
```

The `</dev/null` is not optional. `codex exec` blocks forever reading stdin when stdin is not a
terminal. It prints "Reading additional input from stdin..." and then hangs with no further output,
which reads as a slow model rather than a deadlock.

Ask the reviewer for real defects only, no style preferences, terse and specific, replying with a
bullet list and no preamble. Name the areas it must cover. In later rounds, tell it to attack the
fixes rather than the original problems, or it will keep relitigating round 1. Tell it to say
plainly when it finds nothing, so it does not invent a finding to fill the silence.

### Changes travel as patches, not as write access

No participant edits the working tree directly. A reviewer that wants a change writes a unified diff
to `proposals/<round>-<who>.patch`. The builder runs `git apply --check` on it and then either
applies it or refuses it with a reason written into `COMMS.md`.

This keeps what read-only was buying, which is that nothing lands unexamined and every change has an
author and an argument attached to it. It drops the part that costs, which is one agent hand
transcribing another's findings into edits. That transcription step is where mistakes get
introduced.

The refusals matter more than the applications. A patch that gets rejected leaves a record of why,
and that is the thing git history alone cannot reconstruct later.

Record it in the round like this, in place of the reply block:

    <Agent B> to <Agent A>

    proposals/003-codex.patch

    <the diff, verbatim>

    <Agent A> to itself

    Applied, or refused and why. If refused, what was done instead.

### More than two participants

Give each one its own git worktree of the same repo. It edits freely in its own checkout and the
orchestrator merges. Git already handles concurrent writes to shared files, and it handles them
better than a lock table written by hand. `COMMS.md` holds the argument, git holds the change, and
a commit hash joins the two.

One writer per path per round. Git will merge two agents editing the same file and hand back
something neither of them reviewed. A manifest naming who owns which paths this round is cheap now
and expensive to retrofit.

## 7. The routing log

Every dispatch is recorded in `routing.jsonl` through `routelog.py`, which is the only supported
writer. `ROUTING.md` has the full field list. Three events, not one, because the information arrives
at three different times:

`dispatch` before the work is sent, holding only what is knowable at that moment: the exact task,
the kind, the role, every participant that could have taken it, the one that did, how many findings
are still open, how many rounds this task has already taken, and how long it has already run.

`result` when it ends, in every path including failure, timeout and interruption. A dispatch with no
result line is worse than one never logged, because the gap looks like data.

`decision` when the work is disposed of. This holds `stop` or `continue`, the adoption, and the
reason. Corrections append another decision with the same id rather than editing.

The dispatch line is the only usable input for a router. Everything in `result` is outcome. Do not
feed a model how long a call took or how many findings came back, because neither is known when the
routing decision has to be made. That mistake was made in the first version of this spec and caught
in review.

This exists so a router can later be trained to predict where work goes and, more valuable, when
work is done. That is only possible if the record is written from the first run.

## 8. Closing the session

Stop when the piece of work is done. Do not roll straight into the next thing because it is
obvious; start it in a fresh session.

A conversation is re-read in full on every turn, so a thread that runs twice as long costs roughly
four times as much over its life. None of that can be recovered after the fact. Ending early is the
only lever there is.

Before stopping, write the handoff. `COMMS.md` for the argument, `LOG.md` for what happened,
`DECISIONS.md` for why. Then tell me plainly that the work is done and the session should close.

The test is whether a fresh session could pick this up from the files alone, with nothing explained
to it. If it could not, something that mattered exists only in the conversation. Say so and put it
in a file, rather than keeping the thread alive to hold it.

## 9. How to work with me

Never claim what software does without running it. This has cost me real time more than once. If
something cannot be verified in the environment you have, say so in that sentence rather than
somewhere else.

Ask before anything long or expensive: multi-minute builds, large downloads, bulk operations.

Short answers. I ask when I want more.

When I say stop, stop. Do not carry on with the previous thread.

Do only what was asked. No extra files in my folders, no backup copies. Edit in place. Ask before
creating any new file in a repo, notes and handovers included.

No comments in the code unless I ask for them.

Notes that disagree with the code are worse than no notes. After changing behaviour, grep the docs
for the old description and fix it in the same commit.

Keep your own process out of the repo. No "hours lost", no "I claimed X and was wrong", no account
of how a thing was found. Record the technical finding as a fact about the code and drop the rest.
