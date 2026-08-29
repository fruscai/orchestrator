#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


ACTIVE_ENV = "DUEL_COORDINATOR_ACTIVE"
MAX_ROUNDS = 10
DEFAULT_ROUNDS = 3
NO_FINDINGS = "NO FINDINGS"
UNRESOLVED = 3
SECURITY_OPEN = 4
QUESTIONS_OPEN = 5
# The reviewer tags each finding with one of these. Asking for an exact tag is the only
# honest way to count findings: inferring a count from the shape of prose writes numbers
# that look measured and are not.
SEVERITIES = ("SECURITY", "BLOCKING", "IMPROVEMENT")
QUESTION = "QUESTION"


def parse_command(value):
    command = shlex.split(value)
    if not command:
        raise argparse.ArgumentTypeError("command cannot be empty")
    return command


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run bounded build, review and disposition rounds between two agents."
    )
    parser.add_argument("task")
    parser.add_argument("--agent-a", required=True, type=parse_command)
    parser.add_argument("--agent-b", required=True, type=parse_command)
    parser.add_argument("--builder", required=True, choices=("a", "b"))
    parser.add_argument("--agent-a-name", default="Agent A")
    parser.add_argument("--agent-b-name", default="Agent B")
    parser.add_argument("--review-areas", required=True)
    parser.add_argument("--round-title", action="append", required=True)
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--workdir", type=Path, default=Path.cwd())
    parser.add_argument("--comms", type=Path, default=Path("COMMS.md"))
    parser.add_argument("--task-id", dest="task_id", required=True,
                        help="stable across every round of one task. Every dispatch is recorded "
                             "through routelog.py under this id")
    parser.add_argument("--routelog", type=Path, default=None)
    parser.add_argument("--routing-file", dest="routing_file", type=Path, default=Path("routing.jsonl"))
    parser.add_argument("--available", default=None,
                        help="comma separated, every participant that could have taken this work. "
                             "Defaults to both agent names")
    parser.add_argument("--model-a", dest="model_a", default=None)
    parser.add_argument("--model-b", dest="model_b", default=None)
    return parser.parse_args(argv)


def find_writer(workdir):
    """routelog.py, in the project first, then beside this file, then the one every
    project was copied from."""
    candidates = (
        workdir / "routelog.py",
        Path(__file__).resolve().parent / "routelog.py",
        Path(__file__).resolve().parent.parent / "routelog.py",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def validate_args(args):
    if not 1 <= args.rounds <= MAX_ROUNDS:
        raise ValueError(f"rounds must be between 1 and {MAX_ROUNDS}")
    # Rounds is a ceiling, not a count: a round with no findings ends the run early,
    # so requiring a title per round would demand titles for rounds that never happen.
    if not args.round_title:
        raise ValueError("provide at least one --round-title")
    if len(args.round_title) > args.rounds:
        raise ValueError("more --round-title values than rounds")
    if args.timeout < 1:
        raise ValueError("timeout must be at least 1 second")
    workdir = args.workdir.expanduser().resolve()
    if not workdir.is_dir():
        raise ValueError(f"workdir is not a directory: {workdir}")
    comms = args.comms.expanduser()
    if not comms.is_absolute():
        comms = workdir / comms
    args.workdir = workdir
    args.comms = comms.resolve()
    if not args.task_id.strip():
        raise ValueError("--task-id cannot be blank")
    names = (args.agent_a_name, args.agent_b_name)
    if any("," in name for name in names):
        raise ValueError("agent names cannot contain a comma: --available is a comma separated list")
    if args.agent_a_name == args.agent_b_name:
        raise ValueError("agent names must differ, or the routing log cannot tell them apart")
    args.available = ([value.strip() for value in args.available.split(",") if value.strip()]
                      if args.available else list(names))
    for name in names:
        if name not in args.available:
            raise ValueError(f"--available must include {name!r}, since it could have taken the work")
    writer = args.routelog.expanduser() if args.routelog else find_writer(workdir)
    if writer is None or not writer.is_file():
        # Refusing here rather than running unlogged: a round that leaves no record
        # is the gap the log exists to prevent, and it cannot be filled in later.
        raise ValueError("no routelog.py found. Pass --routelog; there is no unlogged mode")
    args.routelog = writer.resolve()
    routing = args.routing_file.expanduser()
    if not routing.is_absolute():
        routing = workdir / routing
    args.routing_file = routing.resolve()


def acquire_lock():
    identity = hashlib.sha256(str(Path(__file__).resolve()).encode()).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"duel-coordinator-{identity}.lock"
    handle = path.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("another coordinator run is already active")
    return handle


class AgentError(RuntimeError):
    """A turn that ended badly, carrying the status the routing log records.

    The status is an attribute rather than something read back out of the message,
    so the log never depends on the wording of an error string.
    """

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def stop_process_group(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)


def close_pipes(process):
    for pipe in (process.stdin, process.stdout, process.stderr):
        if pipe is not None:
            pipe.close()


def run_agent(command, prompt, workdir, timeout):
    environment = os.environ.copy()
    environment[ACTIVE_ENV] = "1"
    with tempfile.TemporaryDirectory(prefix="duel-turn-") as directory:
        output_path = Path(directory) / "response.txt"
        tokens_path = Path(directory) / "tokens.txt"
        has_prompt = any("{prompt}" in argument for argument in command)
        has_output = any("{output}" in argument for argument in command)
        prepared = [
            argument.replace("{prompt}", prompt)
                    .replace("{output}", str(output_path))
                    .replace("{tokens}", str(tokens_path))
            for argument in command
        ]
        process = subprocess.Popen(
            prepared,
            stdin=subprocess.DEVNULL if has_prompt else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workdir,
            env=environment,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(None if has_prompt else prompt, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            stop_process_group(process)
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                close_pipes(process)
                stdout, stderr = "", ""
            partial = error.stdout or stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode(errors="replace")
            detail = f"\nPartial output:\n{partial.strip()}" if partial.strip() else ""
            raise AgentError(f"agent timed out after {timeout} seconds{detail}", "timeout") from error
        except KeyboardInterrupt:
            stop_process_group(process)
            close_pipes(process)
            raise
        if process.returncode != 0:
            detail = stderr.strip() or stdout.strip() or "no output"
            raise AgentError(f"agent exited with {process.returncode}: {detail}", "failed")
        output = output_path.read_text(encoding="utf-8").strip() if has_output else stdout.strip()
        if not output:
            raise AgentError("agent returned an empty response", "failed")
        return output, read_tokens(tokens_path)


def tagged(text, tag):
    """Lines opening with an exact tag, bullet markers allowed in front of it. Only the
    tag is trusted: nothing is read out of the prose that follows it."""
    found = []
    marker = "[" + tag + "]"
    for line in text.splitlines():
        stripped = line.strip().lstrip("-*").lstrip()
        if stripped.startswith(marker):
            found.append(stripped[len(marker):].strip())
    return found


def severities(review):
    """How many findings of each kind the reviewer marked. A reply that ignores the tags
    counts as nothing, which is why the count stays null unless the tags are actually
    there: an untagged review is unstructured, and guessing at it is what the log is
    meant to avoid."""
    return {name: tagged(review, name) for name in SEVERITIES}


def untagged_lines(review):
    """Non-blank lines carrying none of the tags, bullet markers stripped. A reply
    mixing tagged findings with untagged lines is only partly readable, and the
    unread part could be the finding that mattered."""
    markers = tuple("[" + name + "]" for name in SEVERITIES + (QUESTION,))
    leftover = []
    for line in review.splitlines():
        stripped = line.strip().lstrip("-*").lstrip()
        if stripped and not stripped.startswith(markers):
            leftover.append(stripped)
    return leftover


def shippable(review, counts):
    """Nothing left that stops the work doing what was asked. Improvements do not block:
    the smallest thing that works is what is being built, and there is always something
    that could be better.

    A review with no tags at all is not shippable. It is unstructured, so nothing is
    known about it, and a reviewer that ignores the format would otherwise mark every
    round finished by saying nothing the coordinator can read. A review with tags and
    untagged lines beside them is not shippable either, for the same reason: one
    readable improvement must not launder the lines that cannot be read. Ambiguity
    holds the round open; it never ships.
    """
    if not any(counts.values()):
        return False
    if untagged_lines(review):
        return False
    return not counts["SECURITY"] and not counts["BLOCKING"]


def no_findings(review):
    """The whole reply, exactly the sentinel, exactly as the prompt demands it. The
    sentinel followed by anything else is a contradiction, and a contradiction keeps
    the rounds going rather than recording zero findings."""
    return review.strip() == NO_FINDINGS


class RouteLog:
    """Records every dispatch through routelog.py, which is the only supported writer.

    Run as a subprocess rather than imported: routelog exits the process on each
    validation failure, and imported that would take the coordinator down with it.
    """

    def __init__(self, writer, path, task_id, available, models, workdir):
        self.writer = writer
        self.path = path
        self.task_id = task_id
        self.available = available
        self.models = models
        self.workdir = workdir
        self.ids = []

    def run(self, arguments):
        completed = subprocess.run(
            [sys.executable, str(self.writer), "--file", str(self.path)] + arguments,
            text=True,
            capture_output=True,
            cwd=self.workdir,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no reason given"
            raise RuntimeError(f"routelog refused the record: {detail}")
        return completed.stdout.strip()

    def elapsed(self):
        """Seconds already spent on this task, summed across every earlier run. Read
        from the log rather than counted in memory, so it survives separate runs."""
        if not self.path.exists():
            return 0.0
        mine = set()
        total = 0.0
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "dispatch" and event.get("task_id") == self.task_id:
                    mine.add(event.get("id"))
                elif event.get("event") == "result" and event.get("id") in mine:
                    total += event.get("seconds") or 0.0
        return total

    def dispatch(self, round_number, seq, parent, task, kind, role, participant):
        arguments = [
            "dispatch",
            "--task-id", self.task_id,
            "--round", str(round_number),
            "--seq", str(seq),
            "--task", task,
            "--kind", kind,
            "--role", role,
            "--available", ",".join(self.available),
            "--participant", participant,
            "--rounds-so-far", str(round_number - 1),
            "--elapsed-so-far", f"{self.elapsed():.3f}",
        ]
        if parent:
            arguments.extend(("--parent", parent))
        if self.models.get(participant):
            arguments.extend(("--model", self.models[participant]))
        identifier = self.run(arguments)
        self.ids.append(identifier)
        return identifier

    def result(self, identifier, seconds, status, error=None, findings=None, tokens=None):
        arguments = ["result", "--id", identifier, "--seconds", f"{seconds:.3f}", "--status", status]
        if status != "ok":
            arguments.extend(("--error", (error or "no detail")[:500]))
        if findings is not None:
            arguments.extend(("--findings", str(findings)))
        if tokens is not None:
            arguments.extend(("--tokens", str(tokens)))
        self.run(arguments)


def read_tokens(path):
    """What the agent said it spent, if it said. Each tool reports usage its own way,
    so the command writes the number to {tokens} and the coordinator parses nothing.
    Anything unreadable is left null rather than guessed at: an invented cost is worse
    than a missing one."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip().replace(",", "").replace("_", "")
    try:
        count = int(text)
    except ValueError:
        return None
    return count if count >= 0 else None


def existing_round_count(path):
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    numbers = [int(value) for value in re.findall(r"^Round (\d+) — .+$", text, re.MULTILINE)]
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        raise ValueError("COMMS.md round numbers are not consecutive")
    return len(numbers)


def fence_for(text):
    longest = max((len(match) for match in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def append_round(path, number, title, timestamp, builder, reviewer, prompt, reply,
                 disposition, questions=()):
    date_heading = timestamp.strftime("## %m-%d-%Y")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    headings = re.findall(r"^## \d{2}-\d{2}-\d{4}$", existing, re.MULTILINE)
    if date_heading in headings and headings[-1] != date_heading:
        raise ValueError("current COMMS.md date is not the final date heading")
    prefix = ""
    if not existing:
        prefix = f"{date_heading}\n\n"
    elif date_heading not in headings:
        prefix = f"\n{date_heading}\n\n"
    fence = fence_for(prompt)
    entry = (
        f"{prefix}Round {number} — {title}\n"
        f"{timestamp.strftime('%H:%M')}\n\n"
        f"{builder} to {reviewer}\n\n"
        f"{fence}\n{prompt}\n{fence}\n\n"
        f"{reviewer} to {builder}\n\n"
        f"{reply}\n\n"
        f"{builder} to itself\n\n"
        f"{disposition}\n"
    )
    if questions:
        # In the round itself, not only on a terminal that gets closed. The prompt is
        # recorded verbatim above and carries the tag inside it, so a question is only
        # findable later if it has a heading of its own. Numbered, because the answers
        # are appended as their own block rather than written back over these lines.
        entry += "\nquestions for you\n\n"
        entry += "".join(f"{index}. {question}\n"
                         for index, question in enumerate(questions, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry)
        handle.flush()
        os.fsync(handle.fileno())


def latest_answers(path):
    """What the human said to the last round's questions, if they said anything.

    Read back out of COMMS.md rather than passed on the command line, so the answer the
    next round is built on is the one written down, not one retyped from memory.
    """
    if not path.exists():
        return []
    blocks = re.findall(r"^answers to round \d+\n\n((?:.+\n)+)",
                        path.read_text(encoding="utf-8"), re.MULTILINE)
    if not blocks:
        return []
    return [line.strip() for line in blocks[-1].strip().splitlines() if line.strip()]


def build_proposal_prompt(task, builder, reviewer, prior, round_number, answers=()):
    # Only the last disposition. Joining every prior one made each round carry all the
    # rounds before it, so cost per round climbed while value per round fell.
    prior_text = "No prior rounds." if not prior else prior[-1]
    # Passthrough means the question was put and left unanswered on purpose. It is not
    # the same as never having been asked, and the builder is told the difference.
    answered = ("\n\nAnswers to the questions from the last round:\n"
                + "\n".join(answers)
                + "\nAn answer of Passthrough means it was left to you deliberately."
                if answers else "")
    return (
        f"Task:\n{task}\n\n"
        f"You are {builder}, the builder. {reviewer} is the read-only reviewer.\n"
        "Inspect the current project and build or revise the requested work. Run the checks needed "
        "for every behavioral claim. Do not invoke another agent or this coordinator.\n"
        "Build the smallest thing that actually works. Leave out anything the task does not "
        "require, and say plainly what you left out and why, so the omission is a decision on the "
        "record rather than a gap.\n"
        f"If you need a judgment that is not yours to make, put it on its own line starting with "
        f"[{QUESTION}] and carry on with the rest.\n\n"
        f"Prior dispositions:\n{prior_text}\n\n"
        f"{answered}\n\n"
        f"Produce the round {round_number} proposal for review. State changed files, checks run and "
        "anything not verified."
    )


def build_review_prompt(task, builder, reviewer, proposal, areas, round_number):
    focus = "Attack the fixes from earlier rounds." if round_number > 1 else "Attack the proposal."
    return (
        f"Task:\n{task}\n\n"
        f"You are {reviewer}, the read-only reviewer. {builder} built the proposal below.\n"
        "Do not edit any file. Find real defects only, no style preferences. Be terse and specific. "
        f"Cover these areas: {areas}, and security in every round whether or not it is listed. "
        f"{focus} Reply with a bullet list and no preamble. "
        "Mark anything not verified as unverified. Do not invoke another agent or this coordinator.\n"
        f"Start every finding with exactly one of [{SEVERITIES[0]}], [{SEVERITIES[1]}] or "
        f"[{SEVERITIES[2]}]. Security is anything that lets the wrong party read, write or run "
        "something. Blocking is anything that makes the work fail to do what was asked. Everything "
        "else is an improvement, including things you would do differently. Do not mark something "
        "blocking because it could be better: the smallest thing that works is the thing being "
        "built.\n"
        f"If you need a judgment from the person running this, put it on its own line starting "
        f"with [{QUESTION}].\n"
        f"If there is nothing real to report, reply with exactly {NO_FINDINGS} on the first line and "
        "nothing else. Do not invent a finding to fill the silence.\n\n"
        f"Builder proposal:\n{proposal}"
    )


def build_disposition_prompt(task, builder, proposal, review):
    return (
        f"Task:\n{task}\n\n"
        f"You are {builder}, the builder. Verify each reviewer claim before acting. Do not invoke "
        "another agent or this coordinator.\n"
        f"Fix every confirmed [{SEVERITIES[0]}] and [{SEVERITIES[1]}] finding. Leave "
        f"[{SEVERITIES[2]}] findings alone unless one is a single obvious line, and say which you "
        "left and why. Then run the relevant checks.\n"
        f"Put anything needing a human judgment on its own line starting with [{QUESTION}].\n\n"
        f"Your proposal:\n{proposal}\n\n"
        f"Reviewer reply:\n{review}\n\n"
        "Reply with what actually changed because of the review, and what was left standing and why."
    )


def run_turn(log, command, prompt, workdir, timeout, round_number, seq, parent,
             kind, role, participant, findings_of=None):
    """One dispatch, its result, and the turn itself.

    The result is written on every path out of here, including timeout and Ctrl-C. A
    dispatch that ends without one leaves a gap that reads as work never sent.
    """
    # SIGINT is held from before the dispatch record until the handlers below are in
    # place, so an interrupt cannot land between the record and the try that answers
    # it. A signal that arrives while held is delivered at the restore inside the try.
    held = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    try:
        identifier = log.dispatch(round_number, seq, parent, prompt, kind, role, participant)
        started = time.monotonic()
    except BaseException:
        signal.pthread_sigmask(signal.SIG_SETMASK, held)
        raise
    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, held)
        output, tokens = run_agent(command, prompt, workdir, timeout)
    except AgentError as error:
        log.result(identifier, time.monotonic() - started, error.status, str(error))
        raise
    except KeyboardInterrupt:
        log.result(identifier, time.monotonic() - started, "interrupted", "coordinator interrupted")
        raise
    except BaseException as error:
        log.result(identifier, time.monotonic() - started, "failed", repr(error))
        raise
    seconds = time.monotonic() - started
    log.result(identifier, seconds, "ok",
               findings=findings_of(output) if findings_of else None, tokens=tokens)
    return identifier, output, tokens


def count_findings(review):
    """Null unless the reviewer used the tags. An untagged reply is prose, and a count
    read out of prose is a number nobody should lean on."""
    if no_findings(review):
        return 0
    total = sum(len(found) for found in severities(review).values())
    return total or None


def verdict_line(clean, counts, ship, leftover):
    if clean:
        return "Reviewer found nothing. Stopping rather than running the rounds asked for."
    parts = [f"{len(found)} {name.lower()}" for name, found in counts.items() if found]
    if leftover:
        parts.append(f"{len(leftover)} line(s) the reviewer did not tag")
    summary = ", ".join(parts) if parts else "nothing the coordinator can read as a finding"
    if ship:
        return (f"Findings: {summary}. Nothing blocking left, so this is the smallest "
                "thing that works. Stopping.")
    return f"Findings: {summary}."


def plural(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def cost_line(turns):
    """What the round cost, per participant. A turn whose command did not write
    {tokens} is named as unreported rather than counted as zero."""
    spent = {}
    seen = []
    for name, tokens in turns:
        if name not in seen:
            seen.append(name)
        if tokens is not None:
            spent[name] = spent.get(name, 0) + tokens
    parts = [f"{name} {spent[name]:,}" for name in seen if name in spent]
    silent = [name for name in seen if name not in spent]
    if silent:
        parts.append("not reported by " + " and ".join(silent))
    return "Tokens this round: " + (", ".join(parts) if parts else "none reported")


def near(path, workdir):
    """Written relative to the working directory when it sits underneath it. These
    lines get pasted by hand, and absolute paths make them unreadable."""
    try:
        return str(path.relative_to(workdir))
    except ValueError:
        return str(path)


def print_decisions(log, writer, path, workdir, round_number):
    """The disposition is the human's, so the coordinator prints the lines rather than
    writing them. One judgment fills all three: the review carries the real verdict,
    the other two carry whether the work moved on."""
    if not log.ids:
        return
    print(f"\nRound {round_number} recorded. Say what you made of it, from {workdir}:")
    for identifier in log.ids:
        print(f"  python3 {near(writer, workdir)} --file {near(path, workdir)} "
              f"decision --id {identifier} --stop continue --adoption adopted --by human")
    log.ids.clear()


def main(argv=None):
    if os.environ.get(ACTIVE_ENV):
        print("nested coordinator launch refused", file=sys.stderr)
        return 2
    args = parse_args(argv)
    try:
        validate_args(args)
        completed = existing_round_count(args.comms)
        lock_handle = acquire_lock()
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    agents = {
        "a": (args.agent_a_name, args.agent_a),
        "b": (args.agent_b_name, args.agent_b),
    }
    builder_name, builder_command = agents[args.builder]
    reviewer_key = "b" if args.builder == "a" else "a"
    reviewer_name, reviewer_command = agents[reviewer_key]
    log = RouteLog(
        args.routelog,
        args.routing_file,
        args.task_id,
        args.available,
        {args.agent_a_name: args.model_a, args.agent_b_name: args.model_b},
        args.workdir,
    )
    dispositions = []
    unresolved = False
    security = False
    raised = False
    asked = False
    # Questions asked so far this round. Held outside the try so a turn that fails
    # cannot take the questions already asked before it down with it.
    pending = []
    failure = None
    try:
        for offset in range(args.rounds):
            number = completed + offset + 1
            title = args.round_title[min(offset, len(args.round_title) - 1)]
            proposal_prompt = build_proposal_prompt(
                args.task, builder_name, reviewer_name, dispositions, number,
                latest_answers(args.comms) if offset == 0 else (),
            )
            proposal_id, proposal, build_tokens = run_turn(
                log, builder_command, proposal_prompt, args.workdir, args.timeout,
                number, 1, None, "build", "builder", builder_name,
            )
            pending = tagged(proposal, QUESTION)
            review_prompt = build_review_prompt(
                args.task,
                builder_name,
                reviewer_name,
                proposal,
                args.review_areas,
                number,
            )
            review_id, review, review_tokens = run_turn(
                log, reviewer_command, review_prompt, args.workdir, args.timeout,
                number, 2, proposal_id, "review", "reviewer", reviewer_name,
                findings_of=count_findings,
            )
            pending = pending + tagged(review, QUESTION)
            counts = severities(review)
            # Raised means it is on the record. Open means the last review still has
            # it. A finding that was raised and then fixed is the loop working, not a
            # reason to report the run as unsafe forever.
            if counts["SECURITY"]:
                raised = True
            security = bool(counts["SECURITY"])
            clean = no_findings(review)
            ship = shippable(review, counts)
            done = clean or ship
            fix_tokens = None
            if done:
                # Nothing to dispose of, and no reason to spend a builder turn saying so.
                # The two ways of being done are not the same and the record says which.
                left = sum(len(found) for found in counts.values())
                disposition = ("The reviewer reported no findings. Nothing was changed."
                               if clean else
                               f"Nothing blocking left. {plural(left, 'improvement')} "
                               "recorded and deliberately not acted on.")
            else:
                disposition_prompt = build_disposition_prompt(
                    args.task, builder_name, proposal, review
                )
                _, disposition, fix_tokens = run_turn(
                    log, builder_command, disposition_prompt, args.workdir, args.timeout,
                    number, 3, review_id, "fix", "builder", builder_name,
                )
                pending = pending + tagged(disposition, QUESTION)
            timestamp = datetime.now().astimezone()
            append_round(
                args.comms,
                number,
                title,
                timestamp,
                builder_name,
                reviewer_name,
                review_prompt,
                review,
                disposition,
                pending,
            )
            dispositions.append(disposition)
            print(f"Round {number} complete at {timestamp.strftime('%H:%M')}")
            print(cost_line(
                ((builder_name, build_tokens), (reviewer_name, review_tokens),
                 (builder_name, fix_tokens))
            ))
            print_decisions(log, args.routelog, args.routing_file, args.workdir, number)
            print(verdict_line(clean, counts, ship, untagged_lines(review)))
            if pending:
                # A question that does not stop the run is not a question. The rounds
                # after it would be built on an answer nobody gave.
                asked = True
                print("\nThe agents need a decision from you:")
                for question in pending:
                    print(f"  - {question}")
                pending = []
            if done or asked:
                unresolved = not done
                break
            unresolved = True
    except (OSError, RuntimeError, ValueError, KeyboardInterrupt) as error:
        print(str(error) or "interrupted", file=sys.stderr)
        failure = 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        lock_handle.close()
    if pending:
        # The round broke before its boundary, but these were already asked and an
        # error does not unask them.
        asked = True
        print("\nThe agents need a decision from you:")
        for question in pending:
            print(f"  - {question}")
    sys.stdout.flush()
    if security:
        print("\nA security finding is still open. Do not treat this as finished until "
              "you have checked it yourself.", file=sys.stderr)
    elif raised:
        # Raised and then fixed. Said plainly, because the fix was the builder's claim
        # and a later reviewer going quiet is not the same as you having looked.
        print("\nA security finding was raised earlier and the last review no longer "
              "reports it. Check that yourself before trusting it.", file=sys.stderr)
    if failure == 130:
        if security:
            print("Exit 130 because it was interrupted. The open security finding above "
                  "stands.", file=sys.stderr)
        return 130
    if security:
        return SECURITY_OPEN
    if asked:
        print("\nStopped so you can answer. Fold your answer into the task and run again.",
              file=sys.stderr)
        return QUESTIONS_OPEN
    if failure is not None:
        return failure
    if unresolved:
        # The cap is a stopping point, not a verdict. It exits distinctly so nothing
        # downstream mistakes "ran out of rounds" for "the work is finished".
        print(f"\nStopped after {args.rounds} round(s) with findings still open. "
              "Nothing continues on its own.", file=sys.stderr)
        return UNRESOLVED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
