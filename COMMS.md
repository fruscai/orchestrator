## 08-28-2026

Round 1 — process cleanup and transcript integrity
12:23

Agent A to Agent B

```
Review this project adversarially. Read README.md, duel.py, and tests/test_duel.py. Focus on concrete defects that could break alternating turns, transcript integrity, timeout handling, command execution, or recursion prevention. Do not edit files. Do not praise the design. Return a compact findings table with severity, claim, and exact evidence. Mark anything not reproduced as unverified.
```

Agent B to Agent A

Findings, most severe first. "Reproduced" means I ran a standalone snippet on this machine (Python 3.14.4); everything else is from reading the code and is marked unverified.

| Severity | Claim | Evidence |
|---|---|---|
| High, reproduced | Timeout kills only the direct agent process; anything the agent spawned keeps running in the workdir after the "agent timed out" error | `run_agent` uses `subprocess.run(..., timeout=...)` with no `start_new_session` or group kill (`duel.py:101-110`). Repro: child spawning `/bin/sleep 30` timed out at 2s, the sleep pid was still alive after the kill |
| Medium, reproduced | Timeout error text embeds a bytes repr: `Partial output:\nb'...'` | With `text=True` on POSIX, `TimeoutExpired.stdout` is bytes; `duel.py:112-114` formats it straight into the f-string. Repro output: `"Partial output:\nb'GRANDCHILD 14617'"`. The same string goes into the transcript error record |
| Medium, unverified | Rerunning with the same `--transcript` path appends a second session and its turns to the same file | `append_entry` opens mode `"a"` and nothing truncates (`duel.py:58`). README line 5 says "Each run writes one JSON Lines transcript" |
| Medium, unverified | Recursion prevention is one inherited env var; an agent that clears its environment relaunches the coordinator with no refusal | The only check is `os.environ.get(ACTIVE_ENV)` at `duel.py:125`; the prompt's "Do not invoke another agent" line (`duel.py:89`) is text, not enforcement |
| Low, unverified | An unwritable transcript path crashes with a raw traceback and writes no error record | The session record write (`duel.py:140`) is before the `try`; an OSError from `append_entry` inside the except handler (`duel.py:170`) is also uncaught |
| Low, unverified | stderr from a succeeding agent is dropped from the transcript | Turn records keep `result.stdout` only (`duel.py:118`, `duel.py:162`); README line 5 says every turn records the "full response" |
| Low, unverified | Ctrl-C mid-duel ends the transcript with no error record | Except clause catches `(OSError, RuntimeError)` only, no `finally` (`duel.py:169`) |
| Low, test gap | The alternation test cannot catch the coordinator running agent-a's command for every turn | Both agents get the identical command (`tests/test_duel.py:26,33-35`); round numbers and speaker names are never asserted. No test for timeout, nonzero exit, empty output, or appending to an existing transcript |
| Trivial | Unused import | `import tempfile` at `duel.py:9` |

The full write-up, including the verification snippet's output, is in the plan file at `~/.claude/plans/review-this-project-adversarially-shiny-river.md`. No project files were touched.

Agent A to itself

The timeout path now terminates the direct process group. Transcript reuse, error recording, interruption handling and alternation checks were added. The JSON transcript was later replaced by COMMS.md. Clearing the inherited recursion variable remains possible, so the coordinator lock is still required.

Round 2 — escaped descendants and interrupted runs
12:28

Agent A to Agent B

```
Task:
Assess whether this coordinator safely supports a bounded two-agent technical review. Do not edit files.

You are reviewer, acting as the reviewer. The other participant is implementer.
Review the proposal adversarially. Find concrete defects, unsupported claims, and missed requirements. Treat prior statements as claims to verify.
Do not invoke another agent or this coordinator. Do not edit files unless the task explicitly requires implementation and you are the implementer. Keep the response under 800 words.

Transcript so far:
Round 1, implementer (implementer):
Assessment: this supports a bounded exchange between trusted commands, but it is not a safe containment boundary for untrusted agents.

Verified from [duel.py](~/Downloads/duel-coordinator/duel.py):

- Exactly two fixed roles alternate.
- Rounds are limited to 1–10.
- Each turn has a timeout.
- Timeout handling signals the agent’s process group.
- A non-empty transcript is refused rather than overwritten.
- A lock prevents concurrent runs of this coordinator copy.
- Nested execution is discouraged through `DUEL_COORDINATOR_ACTIVE`.

Safety gaps:

- Agent commands receive the coordinator’s full filesystem permissions and environment. Prompt instructions do not prevent edits, network access, secret access, or arbitrary subprocesses.
- An agent can remove `DUEL_COORDINATOR_ACTIVE` before launching another coordinator. The nesting check is advisory.
- A descendant can create a new session or process group and escape timeout cleanup.
- Output and transcript sizes are unlimited. `communicate()` holds output in memory, and every subsequent prompt includes the accumulated transcript.
- There is no overall session deadline, CPU limit, memory limit, subprocess limit, or output limit.
- Agent names, task text, and prior responses are inserted into prompts without structural isolation, leaving the protocol open to prompt injection.
- Transcript existence checking and append opening are separate operations, so external processes could race or replace the path.

Proposed revision: describe this as an orchestration tool for trusted commands, or add OS-level isolation, a minimal environment, resource limits, an overall deadline, output/transcript caps, and safer transcript creation. Nesting enforcement would need an external boundary rather than an environment variable.

Changed: no files. The proposed conclusion is that the turn count is bounded, but execution is not safely contained.

Uncertain: runtime verification could not be completed in this restricted session. The test run was blocked by the active-coordinator guard and unavailable writable temporary directories, so the process-group cleanup behavior remains supported by code inspection and its test, not by a successful local run.

Write the next reviewer turn only.
```

Agent B to Agent A

Round 1, reviewer (reviewer):

I checked each claim against `duel.py` and `tests/test_duel.py`. Most of the implementer's inventory holds. Three claims need correction, and there are defects the implementer missed.

**Claims verified**

- Two fixed roles alternate (`duel.py:168-186`); rounds 1–10 (`duel.py:45`); per-turn timeout with `killpg` on a new session (`duel.py:123-133`); non-empty transcript refused (`duel.py:164`); flock keyed on the script path (`duel.py:67-76`); env-var nesting guard (`duel.py:149`). All accurate.
- Full inheritance of environment and permissions, unbounded output, prompt-injection surface: accurate.

**Claims to correct**

1. "No overall session deadline" is overstated. Wall clock is bounded to roughly `2 × rounds × (timeout + 2s)` because both rounds and timeout are validated. What is missing is an upper bound on `--timeout` (any positive int passes at `duel.py:47`), not a deadline. The one genuine unbounded case is below (defect 1).
2. "A descendant can create a new session and escape timeout cleanup" is true, but understated. The consequence is worse than a leaked process: it hangs the coordinator (defect 1).
3. "The lock prevents concurrent runs of this coordinator copy" is accurate but the lock has its own problems (defect 4).

**Missed defects**

1. **Hang after timeout.** If any descendant calls `setsid` and keeps the inherited stdout/stderr pipe open, `killpg` at `duel.py:128` and `:132` never reaches it. The final `process.communicate()` at `duel.py:133` has no timeout and waits for pipe EOF, so the coordinator blocks indefinitely. The timeout path is therefore only a bound when the agent tree stays in its session, which is exactly the case the implementer says cannot be assumed. `test_timeout_kills_descendant_process` only spawns a same-group `sleep`, so it cannot detect this.
2. **Ctrl-C orphans the agent.** `start_new_session=True` detaches the agent from the controlling terminal, so SIGINT reaches the coordinator but not the agent. The `KeyboardInterrupt` branch at `duel.py:202-213` writes a record and returns 130 without signalling the process group. The agent keeps running with no timeout at all. The README's "stops when either command fails" does not cover this.
3. **Transcript is writable by the agents.** Agents run with `cwd=workdir` and full permissions; the transcript defaults to `workdir/transcript.jsonl` (`duel.py:40, 54`). An agent can rewrite the on-disk transcript during its turn. The in-memory `entries` list is what feeds later prompts, so the file and the prompts can silently diverge, and the file cannot be treated as an audit record.
4. **Lock file in shared tempdir.** `acquire_lock` opens a predictable path with `"w"` (`duel.py:69-70`). On a shared machine another user can pre-create it and hold the flock forever (permanent "already active"), or plant a symlink that `open("w")` truncates. The lock is also taken before `parse_args`, so `--help` and argument errors are refused while any run is active.
5. **Turn forgery via formatting.** `transcript_text` frames turns as `Round N, speaker (role):` with no delimiter the agent cannot reproduce (`duel.py:82-84`). An agent can emit fake prior turns in its own output; the next prompt presents them as history. This is the concrete form of the injection risk, not just a general concern.
6. **Partial-output handling on timeout.** `error.stdout` at `duel.py:134` is only consulted if `stdout` is falsy after the kill; the second `communicate` returns whatever was buffered, so this is fine, but the `bytes` branch at `:135` is dead code with `text=True`. Minor.

**Missed requirements against the task**

- The task asks whether the tool "safely supports a bounded two-agent technical review." Bounded: yes, on turn count; no, on wall clock (defect 1) and on memory (unbounded output re-embedded each turn). Safe: no, for untrusted commands, agreed.
- Neither README nor code states the trust assumption. The implementer's proposed revision ("describe as orchestration for trusted commands") is the right minimum, and should include defects 1 and 2 since they affect trusted commands too.

**On the implementer's verification gap**

The implementer did not get a test run. I also did not run the suite, since the instruction forbids invoking the coordinator and every test does. The claim that `test_timeout_kills_descendant_process` passes stands unverified by both of us, and even passing it would not exercise defect 1.

**Conclusion**

Agree with the headline: turn count is bounded, execution is not contained. Add: the timeout is not a hard bound either, and interruption leaks the agent. The first two fixes I would require before calling this bounded even for trusted commands are a timeout on the final `communicate()` (with the process abandoned and reported if it still will not exit) and `killpg` in the interrupt path.

Agent A to itself

The final output-pipe wait now has a bound after timeout, and Ctrl-C terminates the active process group. Tests cover both cases. The trust boundary remains: commands inherit the current environment and filesystem permissions, and a descendant that starts a separate process group is outside the cleanup boundary. The earlier transcript framing was replaced by the exact COMMS.md exchange format.

Round 3 — routelog wired into the coordinator
20:49

claude to codex

```
Task:
duel.py must record every dispatch through routelog.py, with a result written on every exit path including timeout and interruption, and the round count must become a ceiling that stops early when the reviewer finds nothing.

You are codex, the read-only reviewer. claude built the proposal below.
Do not edit any file. Find real defects only, no style preferences. Be terse and specific. Cover these areas: correctness, the failure paths that must still write a result, the sentinel used to detect an empty review, and whether the tests actually prove what they claim. Attack the fixes from earlier rounds. Reply with a bullet list and no preamble. Mark anything not verified as unverified. Do not invoke another agent or this coordinator.
If there is nothing real to report, reply with exactly NO FINDINGS on the first line and nothing else. Do not invent a finding to fill the silence.

Builder proposal:
Round 1 proposal: duel.py now records every dispatch through routelog.py, and the
round count became a ceiling rather than a target.

Changed files: duel.py, tests/test_duel.py. Nothing else was touched.

What changed in duel.py

1. Routing. New --task-id turns logging on. Without it nothing is logged and behaviour
   is exactly as before, which is why the original seven tests needed no change on that
   account. With it, each round records three dispatches: build (seq 1, builder),
   review (seq 2, reviewer, parent = the build), fix (seq 3, builder, parent = the
   review). The task field carries the exact prompt sent, not a summary.

2. routelog.py is called as a subprocess, not imported. It calls sys.exit on every
   validation failure, and imported that would kill the coordinator.

3. New RouteLog class. find_writer looks for routelog.py in the workdir, then beside
   duel.py, then one level up. If --task-id is given and no writer is found the run is
   refused with exit 2 rather than running unlogged.

4. elapsed_so_far is read back out of routing.jsonl by summing result seconds for
   dispatches sharing this task_id, so it survives across separate runs rather than
   restarting at zero. rounds_so_far is the round number minus one.

5. New AgentError(RuntimeError) carrying a status attribute. run_agent raises it with
   "timeout" or "failed" instead of a plain RuntimeError, so the log never depends on
   matching the wording of an error message.

6. run_turn writes the result on every exit path: ok, AgentError, KeyboardInterrupt,
   and a catch-all BaseException clause. A dispatch that ends without a result leaves a
   gap that reads as work never sent.

7. Decisions are not written by the coordinator. It prints the three routelog decision
   commands with ids filled in, relative to the workdir. The human is the decider.

8. Early stop. The review prompt now asks for exactly "NO FINDINGS" on the first line
   when there is nothing to report. no_findings() checks that sentinel only. Nothing is
   inferred from bullet counts. On a clean review the builder disposition turn is
   skipped, findings is recorded as 0, and the run stops.

9. --rounds now defaults to 3, ceiling still 10. Because a run can stop early, rounds
   is a ceiling and one --round-title per round is no longer required: at least one is
   required, and the last supplied title is reused for any further rounds.

10. build_proposal_prompt sends only the last disposition instead of joining all of
    them. Round 3 previously re-sent rounds 1 and 2 in full.

11. New exit code 3 for "ran the rounds asked for with findings still open", distinct
    from 0. stdout is flushed before it so the message does not race ahead of the round.

Tests: 14 pass, up from 7. Three of the original seven changed their expected exit code
from 0 to 3, because the fake agent always returns findings and the exit contract
genuinely changed. No other original assertion was touched.

New tests cover: three dispatches with matching results and correct parent chain; a
result written with status timeout when the agent times out; a result written with
status interrupted on SIGINT; early stop on NO FINDINGS producing two dispatches and
findings 0; refusal when --task-id is given with no writer; elapsed_so_far carrying
across two runs; and the proposal prompt carrying only the last disposition.

Not verified: no run has been made against real agents through this path. Every test
uses fake agent scripts. The COMMS.md wording for a clean review round ("The reviewer
reported no findings. Nothing was changed.") is written by the coordinator rather than
by the builder, which is a change in what that section of COMMS.md means.
```

codex to claude

- `duel.py:97-99,463-473` — Logging is optional. Omitting `--task-id` selects `NullLog`, so dispatches run without passing through `routelog.py`, violating “record every dispatch.”

- `duel.py:404-406` — A SIGINT after `log.dispatch()` succeeds but before the `try` begins exits without writing a result. The interruption test waits until the agent starts, so it cannot expose this gap.

- `duel.py:214-215` — The sentinel check accepts `NO FINDINGS.`, mixed case, and `NO FINDINGS` followed by additional findings. Such responses incorrectly stop the rounds and record `findings: 0`; the prompt requires an exact response with nothing else.

- `tests/test_duel.py:286-348` — Failure-path coverage only exercises the first build dispatch and one exact clean sentinel. Reviewer/fix timeout or interruption, the post-dispatch interruption window, contradictory sentinel output, and unlogged invocation are not tested. Full suite execution was unverified because the read-only environment has no writable temporary directory.

claude to itself

What actually changed because of the review, all four findings confirmed against the code before acting:

**Finding 1 (optional logging) — confirmed, fixed.** `--task-id` is now required and `NullLog` is deleted, along with the `enabled` flag and the unlogged branch in `validate_args` and `main`. Every run records every dispatch through `routelog.py` or is refused; the refusal message now says "there is no unlogged mode" instead of suggesting dropping `--task-id`. Required by the task's own wording — "record every dispatch" leaves no room for an opt-out. `base_command` in the tests now carries a task id, the two tests that built arguments by hand gained one, all three test classes skip when no writer exists, and a new test asserts that omitting `--task-id` exits 2.

**Finding 2 (SIGINT window between dispatch and try) — confirmed, fixed.** `run_turn` now blocks SIGINT before writing the dispatch record and restores the mask as the first statement inside the try, so a signal arriving in the old window is held and delivered where the handlers that write a result are already in place. A new test makes this deterministic rather than racy: a stub writer sends SIGINT to the coordinator from inside the dispatch subprocess itself — while the mask is held — then delegates to the real `routelog.py`; the test asserts one dispatch, one result with status `interrupted`, and exit 130.

**Finding 3 (lax sentinel) — confirmed, fixed.** `no_findings` is now `review.strip() == "NO FINDINGS"`: whole reply, exact case, no period stripping. Ambiguity resolves toward continuing the rounds, never toward recording zero findings. A new test drives `NO FINDINGS.`, `No findings`, and `NO FINDINGS` followed by a bullet through a full run and asserts each produces three dispatches, exit 3, and a review result whose findings is not 0.

**Finding 4 (coverage) — partially fixed.** Added: the reviewer-timeout test (build result `ok`, review result `timeout`, exit 1), the dispatch-window interrupt test, the contradictory-sentinel test, and the omitted-task-id refusal test. Not added: a fix-turn timeout/interrupt test — all three turns go through the identical `run_turn` path, so the reviewer-timeout test already exercises a non-first dispatch and a third variant would test the same lines again.

Also changed: README's "one title per round are required" line and the example invocation disagreed with the code after these changes; both were updated in the same pass (task id required, rounds as a ceiling, no unlogged mode).

**Left standing:** a second Ctrl-C arriving during the result write inside an except handler could still skip that write. The reviewer's claim was the dispatch-to-try window, which is now closed; closing the double-interrupt case would mean holding SIGINT across the result writes too, and I left that for a finding rather than expanding scope.

**Not verified:** the test suite was not executed this round. Command execution requiring approval — including every `python3` invocation — is blocked in this environment, so the suite run, and even a compile check, could not happen. Every changed region was re-read line by line after editing and the removed-symbol grep is clean, but the 18 tests (14 prior plus 4 new, with several existing ones now running under mandatory logging) are unrun, and the claim that they pass is not one I can make.

## 08-29-2026


## 08-29-2026

Round 4 — the first report over the training log
09:39

claude to codex

```
Task:
report.py must read training.jsonl and print an honest plain English summary: only human decisions counted towards how work was received, the highest rev of a correction winning, unknown values never shown as zero, and the reader warned when the numbers compare jobs rather than agents.

You are codex, the read-only reviewer. claude built the proposal below.
Do not edit any file. Find real defects only, no style preferences. Be terse and specific. Cover these areas: correctness of the counting, the rev tie-break, null versus zero, and whether the untested branches actually work. Attack the proposal. Reply with a bullet list and no preamble. Mark anything not verified as unverified. Do not invoke another agent or this coordinator.
If there is nothing real to report, reply with exactly NO FINDINGS on the first line and nothing else. Do not invent a finding to fill the silence.

Builder proposal:
Round 1 proposal: report.py, a plain English summary of the training log.

Changed files: report.py is new. collect.py gained two lines so the root's own
routing.jsonl is collected alongside the project ones; without it, work on the shared
scripts would be logged and then never gathered.

What report.py does

Reads training.jsonl and prints counts as sentences. It is deliberately not a model.
The point is that it can be read by eye long before there is enough data to train
anything, because reading it is how the fields get corrected.

Structure

- load() groups records into dispatches, results and decisions, keyed on the pair of
  project and id. Ids are generated per project, so an id alone does not identify a
  dispatch once projects are read together.
- settled() returns the decision that stands, which is the one with the highest rev.
  Corrections are appended rather than edited, so the highest rev wins and stays
  unambiguous when two land in the same second.
- describe_work() reports, per participant, what kinds of work they were given and how
  many of those you judged, split into kept, kept part of, and refused. Only decisions
  with by == "human" are counted. A builder judging what it kept from its reviewer is
  grading the agent that just criticised it.
- describe_cost() reports median seconds per turn and total tokens, naming how many
  turns did not report tokens rather than treating those as zero.
- describe_confound() warns when no kind of work has gone to more than one
  participant, because in that case the numbers compare the jobs and not the agents.
- describe_gaps() names dispatches with no result, dispatches with no decision,
  decisions made by the builder rather than by you, and unreadable lines.

Checks run

Executed against the real training.jsonl, six records, three dispatches. Output was
read and two wording bugs were found and fixed: "dispatchs" from a pluraliser that only
appended "s", and "3 dispatches is waiting" from a hardcoded singular verb. plural()
now handles ch/sh/s/x/z endings and verb() picks the agreement.

Not verified

- No test file exists for report.py at all. Every claim above rests on one run against
  one small log.
- The rev tie-break has never been exercised: no correction has ever been written, so
  settled() has only ever seen lists of length zero or one.
- Only "adopted" has ever appeared in the data. The partial and refused branches have
  never run.
- describe_cost uses statistics.median on a list that is empty when no result carries
  seconds; the guard is "if not seconds: continue", which has not been hit.
- describe_confound uses set.intersection across participants and returns nothing when
  a shared kind exists. The behaviour with three or more participants is unexamined.
- No dispatch in the data has status other than ok, so the failed-turn counting is
  unrun.
```

codex to claude

- `settled()` does not make equal highest revisions unambiguous: `max()` silently selects the first record, so a later correction with the same `rev` loses. Verified with conflicting `rev: 2` decisions.
- A null `rev` crashes `settled()` with `TypeError` when compared with an integer. Verified.
- A human decision with missing or unknown `adoption` is counted as judged and printed as `kept 0`, misrepresenting an unknown value as zero. Verified.
- `describe_cost()` prints nothing for a participant when all `seconds` values are unknown, even when tokens are known, so the token total and missing-time condition disappear. Verified.
- `describe_confound()` requires one work kind shared by every participant. With three participants whose kinds overlap pairwise, it falsely says the figures compare jobs rather than agents and claims no same kind went “to both.” Verified.

claude to itself

Every form of python invocation (project dir, scratchpad, absolute path, trivial `-c`) hits the approval gate, and this session is non-interactive, so nobody can grant it. I cannot execute the checks; I've verified the edits by reading the resulting code instead, and I'm reporting that limitation plainly rather than claiming a run happened.

## What changed because of the review

All five findings were confirmed by reading the code, and all five are fixed in report.py:

1. **Equal-rev tie now goes to the later record.** `settled()` no longer uses `max()`, which keeps the first of equal maxima. It now iterates in file order with `>=`, so between equal revs the record appended last wins — matching the append-only correction model. (`report.py:47`)

2. **Null rev no longer crashes.** `record.get("rev", 0)` returned `None` when the field was present but null, and comparing `None` with an int raises TypeError. Any rev that is not a number is now treated as zero. (Same function.)

3. **Unknown adoption is no longer printed as "kept 0".** A human decision whose `adoption` is missing or unrecognized is no longer counted in `judged`; it is reported separately as "N decisions did not say how the work was received and are not counted." Only decisions with adopted, partial, or refused feed the kept/part/refused counts. (`report.py:84-107`)

4. **A participant with no reported seconds no longer vanishes from the cost section.** The `if not seconds: continue` is gone. The line now says "no turn reported how long it took" and still prints the token total and the did-not-report count when tokens are known. (`report.py:118-121`)

5. **The confound warning now checks whether any kind reached more than one participant**, not whether one kind is shared by all of them. It counts, per kind, how many participants' kind-sets contain it; the warning fires only when every kind belongs to exactly one participant. The wording changed from "goes to both" to "goes to more than one participant," which is also correct for three or more. (`report.py:132-149`)

## What was left standing and why

- The overall structure, `load()`, `plural()`/`verb()`, `describe_gaps()`, and `main()` — no finding touched them.
- collect.py — read in full; the review raised nothing against it and I made no change there.
- In `describe_work`, "kept 0" can still print when kept is genuinely zero but refusals exist (e.g. "kept 0, refused 2"). That is a known zero, not an unknown shown as zero, so it stays.

## Not verified

- **No check was run.** Every python3 invocation in this session requires approval that cannot be granted non-interactively, so the fixed code has not been executed — not against the real training.jsonl and not against synthetic records for the tie, null-rev, unknown-adoption, tokens-without-seconds, or three-participant cases. The claims above rest on reading the code, which is exactly the failure mode the review just caught me in once. The first action when execution is available should be `python3 report.py` plus a synthetic log exercising those five paths.
- The five untested paths listed in the round 1 proposal (tie-break, partial/refused branches, empty-seconds guard, multi-participant confound, failed-turn counting) remain unexercised for the same reason, though three of them were rewritten this round.

Round 5 — smallest working thing, security, and questions
09:51

claude to codex

```
Task:
The coordinator must select the smallest working thing, never leave a security finding behind, and stop for a human question every round it is asked one.

You are codex, the read-only reviewer. claude built the proposal below.
Do not edit any file. Find real defects only, no style preferences. Be terse and specific. Cover these areas: the severity rule, whether an untagged or malformed review can be read as shippable, the exit code precedence, and whether the tests prove what they claim, and security in every round whether or not it is listed. Attack the fixes from earlier rounds. Reply with a bullet list and no preamble. Mark anything not verified as unverified. Do not invoke another agent or this coordinator.
Start every finding with exactly one of [SECURITY], [BLOCKING] or [IMPROVEMENT]. Security is anything that lets the wrong party read, write or run something. Blocking is anything that makes the work fail to do what was asked. Everything else is an improvement, including things you would do differently. Do not mark something blocking because it could be better: the smallest thing that works is the thing being built.
If you need a judgment from the person running this, put it on its own line starting with [QUESTION].
If there is nothing real to report, reply with exactly NO FINDINGS on the first line and nothing else. Do not invent a finding to fill the silence.

Builder proposal:
Round 1 proposal: the loop now selects the smallest working thing, refuses to leave a
security finding behind, and stops for a human question.

Changed files: duel.py and tests/test_duel.py in duel-coordinator. Nothing else.

The rule

The reviewer must start every finding with exactly [SECURITY], [BLOCKING] or
[IMPROVEMENT]. Security is anything letting the wrong party read, write or run
something. Blocking is anything making the work fail to do what was asked. Everything
else is an improvement. The review prompt says explicitly not to mark something blocking
because it could be better.

shippable() is true when there is no security and no blocking finding. Improvements do
not hold a round open, which is what makes "smallest thing that works" a rule the
coordinator enforces rather than an instruction an agent can drift from.

An untagged review is never shippable. A reviewer ignoring the format has said nothing
the coordinator can read, and treating that as nothing-to-fix would let a broken
reviewer mark every round finished. This was found by running the suite: ten tests
failed on the first version, which had exactly that hole.

Security

A security finding sets a flag that survives the rest of the run and returns exit 4,
ahead of every other outcome, with a message saying not to treat the work as finished
without checking. It fires whether or not the builder claims to have fixed it.

Questions

Any agent can put a line starting with [QUESTION] in its reply. Questions from all three
turns are collected, printed under a heading, and the run stops with exit 5. A question
that does not stop the run is not a question: the rounds after it would rest on an
answer nobody gave.

Findings count

routelog's findings field was null on every record ever written, because nothing could
count prose honestly. It is now the number of tagged findings, and still null when the
reviewer did not use the tags. Only structure is counted; nothing is inferred from the
shape of the text.

Exit codes now: 0 done, 1 error, 2 usage, 3 rounds used up with blocking findings open,
4 security raised, 5 waiting on a human answer, 130 interrupted.

Checks run

24 tests pass, up from 19. Five new ones: only-improvements exits 0 in one round and
records findings 1; a blocking finding runs all three rounds and exits 3; a security
finding exits 4 with the warning; an untagged review exits 3 and records findings null;
a question stops after round 1, prints the question and exits 5.

Not verified

- No round has been run against real agents with the new prompts. Whether codex actually
  applies the tags consistently, and whether it agrees with these definitions of
  security and blocking, is unknown.
- tagged() strips leading "-" and "*" then matches the tag at the start. A finding whose
  tag appears mid-line is not counted, and a reply that mentions a tag inside prose
  would be.
- The interaction between a question and a security finding in the same round is
  ordered by exit code precedence only; both are printed, but only one code is returned.
- No test covers a reviewer emitting two different tags on one line.
```

codex to claude

- [BLOCKING] A mixed review such as `- [IMPROVEMENT] minor` plus an untagged or malformed blocking/security finding is treated as shippable. `shippable()` only requires one recognized tag, so the claimed “untagged review is never shippable” rule is incomplete.
- [BLOCKING] Exit-code precedence does not preserve security across failures. After a security finding, a later-round agent or logging error returns exit 1 immediately, bypassing the final security check and exit 4.
- [BLOCKING] A `[QUESTION]` in the builder proposal does not stop further turns. The coordinator still invokes the reviewer and possibly the disposition turn; if either fails, it returns exit 1 without presenting the already-asked question.
- [IMPROVEMENT] The tests do not prove the stated precedence or persistence claims: the security test uses one round only, the question test asks from the reviewer only, and no test combines a prior security finding or proposal question with a later failure.

claude to itself

All three [BLOCKING] findings verified as real and fixed. The suite could not be executed: every form of `python3` invocation was refused by this session's permission gate, so the checks below are claims about code I read, not code I ran.

**What changed because of the review**

- **Mixed reviews no longer ship.** `shippable()` now takes the review text as well as the counts and refuses when `untagged_lines()` finds any non-blank line that carries none of the four tags after bullet stripping. One readable `[IMPROVEMENT]` no longer launders an untagged line beside it; ambiguity holds the round open and worst-cases to exit 3, never to a false ship. The verdict line names the untagged lines so the human sees why the round stayed open.
- **Security survives later failures.** The `security` flag is now set immediately after the review turn, before the disposition runs, and the exception handler records the failure instead of returning. The final exit logic runs on every path: after a security finding, a later agent or logging error prints its error and still exits 4 with the warning.
- **Questions survive later failures.** `pending` is accumulated turn by turn — proposal questions right after the build, review questions right after the review, disposition questions after the fix — and lives outside the `try`. A reviewer or disposition crash now prints the error, then the already-asked questions, and exits 5 instead of 1.
- **Three new tests**, one per fix: a `[IMPROVEMENT]` plus an untagged line exits 3 and names the untagged line; a round-1 security finding followed by a round-2 builder crash exits 4 with both the crash and the warning on stderr; a proposal question followed by a reviewer crash prints the question and exits 5. The [IMPROVEMENT] finding is subsumed by these — the multi-round security test and the proposal-sourced-question test are exactly the gaps it named, so nothing of it was left standing.

**What was left standing and why**

- The coordinator still runs the reviewer and disposition turns after a proposal question, stopping at the round boundary. That is the design the proposal prompt states ("carry on with the rest"): the round's record stays complete and the review of the built work is still worth having. The defect was only the failure path losing the question, and that is fixed.
- `count_findings` still counts only tagged findings, so a mixed review records the tagged count while refusing to ship. Counting the untagged lines would be inferring findings from prose, which the log deliberately refuses.
- Consequence of the stricter rule, on the record: a reviewer that wraps one finding across multiple lines now keeps the round open, because a continuation line is indistinguishable from an untagged finding. It fails toward exit 3, never toward shipping.

[QUESTION] When Ctrl-C lands after a security finding was raised, the run now prints the security warning but returns 130, not 4 — interrupt semantics for shells and wrappers won over the stated "4 ahead of every other outcome." Should security outrank the interrupt code too?

[QUESTION] The checks were not run: `python3` requires an approval this non-interactive session cannot grant, and I will not claim a green suite I never saw. Run `python3 -m unittest discover -s tests` from the project root — 27 tests should collect (24 prior plus 3 new) — before treating any of the above behavioral claims as verified.

## 08-31-2026

Round 6 — alternating the builder and per-role commands
00:33

claude to codex

```
Task:
Add --builder auto to orchestrator.py, which alternates the builder across tasks and keeps it fixed within one task, plus per-role commands --agent-a-review and --agent-b-review so the agent that reviews can be invoked read-only while the agent that builds is not. The work is already implemented in choose_builder and the agents dict in main. Verify it rather than rewriting it.

You are codex, the read-only reviewer. claude built the proposal below.
Do not edit any file. Find real defects only, no style preferences. Be terse and specific. Cover these areas: correctness of the builder choice, what happens with no log or a corrupt one, and whether the per-role commands can leave an agent invoked with the wrong permissions, and security in every round whether or not it is listed. Attack the fixes from earlier rounds. Reply with a bullet list and no preamble. Mark anything not verified as unverified. Do not invoke another agent or this coordinator.
Start every finding with exactly one of [SECURITY], [BLOCKING] or [IMPROVEMENT]. Security is anything that lets the wrong party read, write or run something. Blocking is anything that makes the work fail to do what was asked. Everything else is an improvement, including things you would do differently. Do not mark something blocking because it could be better: the smallest thing that works is the thing being built.
If you need a judgment from the person running this, put it on its own line starting with [QUESTION].
If there is nothing real to report, reply with exactly NO FINDINGS on the first line and nothing else. Do not invent a finding to fill the silence.

Builder proposal:
Round 6 proposal.

The requested work was already in the working tree and reading it confirms it does what the task says. `--builder auto` (orchestrator.py:53) is resolved in main before any dispatch by `choose_builder` (orchestrator.py:364), which reads routing.jsonl under the coordinator lock: the task's own last build dispatch wins, so a task resumed in a separate run keeps its builder; otherwise the choice alternates off the last other task's build dispatch; only `kind == "build"` events count, unreadable lines are skipped, and an unrecognized participant falls back to "a". The per-role commands (orchestrator.py:49-52) land in the agents dict as a third slot defaulting to the build command (orchestrator.py:659-662); the builder's build and fix turns use slot 1 and the reviewer's turn uses slot 2 (orchestrator.py:668-670), so the review-only invocation is used exactly when that agent reviews. The tests cover this with six choose_builder unit tests (empty log, alternation both ways, task stickiness, review dispatches ignored, unreadable line, renamed participant) and one integration test that runs the coordinator twice with `--builder auto` and asserts the build participants alternate; I traced its helpers and flow and they are wired correctly.

Changed files this round: README.md only. Its prose said to choose the builder side before the first round, which contradicts auto, so I replaced that sentence with a description of the two new flags. orchestrator.py and tests/test_orchestrator.py were already changed before this round and I changed nothing in them; routing.jsonl gained this run's own dispatch record, written by the coordinator, not by me.

Checks run: static only — the full diff against HEAD, a line-by-line read of choose_builder, main's wiring, and the new tests, and a grep of every doc for stale descriptions of the flags.

Not verified: the test suite was not executed. Python invocation is approval-gated in this round's sandbox — `python3`, `/usr/bin/python3`, sandboxed and not, were all refused — so every behavioral claim above rests on reading, not running. Separately, the integration tests inherit `DUEL_COORDINATOR_ACTIVE=1` when launched from inside a coordinator turn and orchestrator.py refuses the nested launch, a pre-existing property of the whole suite, so the suite must be run outside a coordinator round regardless.

Left out: no edits to orchestrator.py or the tests, because the task said verify rather than rewrite and reading found nothing wrong; the README example still shows `--builder a`, which remains a valid invocation now that the prose covers auto; no entries in DECISIONS.md or LOG.md, because those record the human's judgments. The README wording was matched to the file's own surrounding sentences because LEXICON.md is unreadable from this sandbox.

[QUESTION] No round can execute the test suite while python is approval-gated here, so verification by execution has to come from you: run `python3 tests/test_orchestrator.py` outside a coordinator turn, or grant python approval to these rounds — which do you want?
```

codex to claude

- [BLOCKING] Unverified at runtime: a corrupt log line containing valid non-object JSON such as `null` or `[]` makes `event.get(...)` raise `AttributeError`. `choose_builder()` runs outside `main()`’s error handler, so `--builder auto` exits with a traceback instead of choosing a builder or reporting a controlled error (`orchestrator.py:380-384, 663-667`).
- [SECURITY] Unverified at runtime: builder commands retain write access to `routing.jsonl`, so a builder can append forged build dispatches and control which command receives build permissions on later automatic runs. The coordinator trusts `task_id` and `participant` fields without authenticating the record (`orchestrator.py:376-395`).

claude to itself

ROUTING.md makes no claim about malformed lines, so no doc contradicts the fix. Both findings are now dealt with; here is the disposition.

What changed because of the review.

The [BLOCKING] finding is confirmed by reading: `json.loads` accepts `null`, `[]`, quoted strings and bare numbers, the `except json.JSONDecodeError` never fires on them, and `choose_builder` runs at orchestrator.py:664 — after the first error handler closes at 658 and before the round-loop try opens at 688 — so the AttributeError escapes `main` as a traceback. Fixed by treating non-dict JSON as unreadable, and in all three readers of the file rather than only the cited one, because the identical crash sits one call later: `RouteLog.elapsed` reads the same file on the first dispatch of the same run and its AttributeError is also uncaught (the round-loop handler lists OSError, RuntimeError, ValueError and KeyboardInterrupt only), and routelog.py's `read_events` fed the `null` event into `dispatch_ids`, crashing the writer subprocess so every append was refused. Each fix is the same two-line `isinstance(event, dict)` guard. The unreadable-line unit test now includes `null`, `[]`, `"quoted"` and `7`, and a new integration test seeds the log with `null` and `[]` and asserts an auto run completes with Agent A chosen.

The [SECURITY] finding is confirmed as a fact but left standing in code, deliberately. The README's own trust model (lines 19-21) says the commands are trusted local programs the coordinator does not isolate; within that model no in-band authentication is real, because any signing key or side-state the coordinator could check is readable and writable by the same-user builder process, so signing the log would be assurance, not security. The lever that actually works already exists: `--routing-file` can put the log where the agent commands cannot write. What changed is the README's routing-log section, which now states plainly that `--builder auto` trusts the log, that any command able to write `routing.jsonl` can forge the choice, and that `--routing-file` moves it out of reach.

Checks run: none executed. Python is approval-gated again this round — `python3` and `/usr/bin/python3` both refused — so every claim above rests on reading. A standalone verification script exercising all three readers against a junk-seeded log is written at the scratchpad path `verify_choose.py` and could not be run. I did not strip `DUEL_COORDINATOR_ACTIVE` to force the integration tests, since that would be invoking this coordinator from inside a round.

[QUESTION] Verification by execution still has to come from you: run `python3 -m unittest discover -s tests -v` outside a round, or grant python approval to these rounds.
[QUESTION] Should routing.jsonl's default location move outside the working tree, or does it stay in-repo — tracked and collected by collect.py — with `--routing-file` as the documented opt-out? The forgery finding is only closed by the layout decision, not by code.

questions for you

1. No round can execute the test suite while python is approval-gated here, so verification by execution has to come from you: run `python3 tests/test_orchestrator.py` outside a coordinator turn, or grant python approval to these rounds — which do you want?
2. Verification by execution still has to come from you: run `python3 -m unittest discover -s tests -v` outside a round, or grant python approval to these rounds.
3. Should routing.jsonl's default location move outside the working tree, or does it stay in-repo — tracked and collected by collect.py — with `--routing-file` as the documented opt-out? The forgery finding is only closed by the layout decision, not by code.
