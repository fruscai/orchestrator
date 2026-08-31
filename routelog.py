"""Append dispatch, result and decision events to a routing log.

The three events exist because the information arrives at three different times. Only the
dispatch event holds what is knowable before work is sent, which is what makes it the only
usable input for a router trained on this log later. ROUTING.md has the full field list.
"""

import argparse
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone

KINDS = ("build", "review", "fix", "research", "scaffold")
ROLES = ("builder", "reviewer")
STATUSES = ("ok", "failed", "timeout", "interrupted")
STOPS = ("stop", "continue")
ADOPTIONS = ("adopted", "refused", "partial", "none")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path, record):
    """Append one JSON object as a line. Opened per call so a crash cannot lose
    earlier lines, O_APPEND so concurrent writers cannot interleave, written in a
    loop because a single os.write can be short, and synced so a line that was
    reported as written survives a crash."""
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    data = line.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        while data:
            data = data[os.write(fd, data):]
        os.fsync(fd)
    finally:
        os.close(fd)
    return record


def read_events(path):
    """Every well formed event, in file order. Malformed lines are skipped rather
    than raising, since a log with one bad line is still worth appending to."""
    events = []
    if not os.path.exists(path):
        return events
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def dispatch_ids(events):
    return {e.get("id") for e in events if e.get("event") == "dispatch"}


def count(events, kind, ident):
    return sum(1 for e in events if e.get("event") == kind and e.get("id") == ident)


def require(condition, message):
    if not condition:
        sys.exit("routelog: " + message)


def positive(name, value, allow_zero=True):
    if value is None:
        return
    if isinstance(value, float) and not math.isfinite(value):
        sys.exit("routelog: " + name + " must be a finite number")
    floor = 0 if allow_zero else 1
    require(value >= floor, name + " cannot be less than " + str(floor))


def cmd_dispatch(a):
    require(a.task.strip(), "task cannot be empty, and must be the exact request rather than a summary")
    require(a.participant in a.available,
            "the chosen participant must appear in --available, otherwise the choice has no alternatives to learn from")
    require(a.task_id.strip(), "task-id cannot be empty: it is what links dispatches across rounds")
    positive("round", a.round, allow_zero=False)
    positive("seq", a.seq, allow_zero=False)
    positive("open-findings", a.open_findings)
    positive("rounds-so-far", a.rounds_so_far)
    positive("elapsed-so-far", a.elapsed_so_far)
    events = read_events(a.file)
    if a.parent is not None:
        require(a.parent in dispatch_ids(events), "no dispatch with id " + a.parent + " to be the parent of this one")
    record = {
        "event": "dispatch",
        "id": uuid.uuid4().hex[:12],
        "task_id": a.task_id,
        "round": a.round,
        "seq": a.seq,
        "parent": a.parent,
        "started": now(),
        "task": a.task,
        "kind": a.kind,
        "role": a.role,
        "available": a.available,
        "participant": a.participant,
        "model": a.model,
        "open_findings": a.open_findings,
        "rounds_so_far": a.rounds_so_far,
        "elapsed_so_far": a.elapsed_so_far,
    }
    append(a.file, record)
    print(record["id"])


def cmd_result(a):
    events = read_events(a.file)
    require(a.id in dispatch_ids(events), "no dispatch with id " + str(a.id) + " in " + a.file)
    require(count(events, "result", a.id) == 0,
            "dispatch " + a.id + " already has a result. A dispatch ends once")
    require(a.status == "ok" or a.error,
            "--error is required unless the status is ok, since a failure with no reason teaches nothing about escalation")
    positive("seconds", a.seconds)
    positive("findings", a.findings)
    positive("tokens", a.tokens)
    append(a.file, {
        "event": "result",
        "id": a.id,
        "ended": now(),
        "seconds": a.seconds,
        "status": a.status,
        "error": a.error,
        "findings": a.findings,
        "tokens": a.tokens,
    })


def cmd_decision(a):
    events = read_events(a.file)
    require(a.id in dispatch_ids(events), "no dispatch with id " + str(a.id) + " in " + a.file)
    require(count(events, "result", a.id) == 1,
            "dispatch " + a.id + " has no result yet. Record what came back before disposing of it")
    require(a.adoption not in ("refused", "partial") or a.reason,
            "--reason is required for refused and partial, or the label records what was rejected without what makes it rejectable")
    # A correction is a new decision with a higher rev. Highest rev wins, which is
    # unambiguous even when two decisions share a second on the clock.
    rev = count(events, "decision", a.id)
    require(rev == 0 or a.reason, "correcting a decision needs --reason saying what the earlier one got wrong")
    append(a.file, {
        "event": "decision",
        "id": a.id,
        "rev": rev,
        "at": now(),
        "stop": a.stop,
        "adoption": a.adoption,
        "reason": a.reason,
        "by": a.by,
    })


def build_parser():
    p = argparse.ArgumentParser(prog="routelog", description=__doc__)
    p.add_argument("--file", default="routing.jsonl")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("dispatch", help="record work about to be sent, before sending it")
    d.add_argument("--task-id", required=True, dest="task_id",
                   help="stable across every round of one task, so a stopping sequence can be reconstructed")
    d.add_argument("--round", type=int, required=True)
    d.add_argument("--seq", type=int, required=True)
    d.add_argument("--parent", default=None)
    d.add_argument("--task", required=True)
    d.add_argument("--kind", choices=KINDS, required=True)
    d.add_argument("--role", choices=ROLES, required=True)
    d.add_argument("--available", required=True,
                   type=lambda s: [x.strip() for x in s.split(",") if x.strip()])
    d.add_argument("--participant", required=True)
    d.add_argument("--model", default=None)
    d.add_argument("--open-findings", type=int, default=0, dest="open_findings")
    d.add_argument("--rounds-so-far", type=int, default=0, dest="rounds_so_far")
    d.add_argument("--elapsed-so-far", type=float, default=0.0, dest="elapsed_so_far")
    d.set_defaults(func=cmd_dispatch)

    r = sub.add_parser("result", help="record what came back, in every path including failure")
    r.add_argument("--id", required=True)
    r.add_argument("--seconds", type=float, required=True)
    r.add_argument("--status", choices=STATUSES, required=True)
    r.add_argument("--error", default=None)
    r.add_argument("--findings", type=int, default=None)
    r.add_argument("--tokens", type=int, default=None)
    r.set_defaults(func=cmd_result)

    c = sub.add_parser("decision", help="record the disposition, which carries the labels")
    c.add_argument("--id", required=True)
    c.add_argument("--stop", choices=STOPS, required=True)
    c.add_argument("--adoption", choices=ADOPTIONS, required=True)
    c.add_argument("--reason", default=None)
    c.add_argument("--by", choices=("human", "builder"), required=True)
    c.set_defaults(func=cmd_decision)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
