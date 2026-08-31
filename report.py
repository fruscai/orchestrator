"""Read the training log and say plainly what it holds.

Counts, not a model. The point is to be readable by eye long before there is enough
here to train anything, because reading it is how the fields get corrected.

    python3 report.py

Only decisions made by a human are counted towards how work was received. A builder
judging what it kept from its reviewer is grading the agent that just criticised it.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path


def load(path):
    """Records grouped by the dispatch they belong to. Ids are generated per project,
    so the project and the id together are what identify a dispatch."""
    dispatches = {}
    results = {}
    decisions = {}
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            key = (record.get("project"), record.get("id"))
            event = record.get("event")
            if event == "dispatch":
                dispatches[key] = record
            elif event == "result":
                results[key] = record
            elif event == "decision":
                decisions.setdefault(key, []).append(record)
    return dispatches, results, decisions, skipped


def settled(decisions):
    """The decision that stands. A correction is appended rather than edited, so the
    highest rev wins, and between equal revs the one appended last. A rev that is
    missing or not a number counts as zero rather than crashing the report."""
    best = None
    best_rev = None
    for record in decisions:
        rev = record.get("rev")
        if not isinstance(rev, (int, float)):
            rev = 0
        if best is None or rev >= best_rev:
            best, best_rev = record, rev
    return best


def plural(count, word):
    ending = "es" if word.endswith(("ch", "sh", "s", "x", "z")) else "s"
    return f"{count} {word}" + ("" if count == 1 else ending)


def verb(count, singular, many):
    return singular if count == 1 else many


def describe_work(dispatches, results, decisions):
    """What each participant was given, and how what came back was received."""
    lines = []
    people = sorted({record["participant"] for record in dispatches.values()})
    for person in people:
        theirs = {key: record for key, record in dispatches.items()
                  if record["participant"] == person}
        kinds = {}
        for record in theirs.values():
            kinds[record["kind"]] = kinds.get(record["kind"], 0) + 1
        did = ", ".join(f"{plural(count, 'time')} on {kind}"
                        for kind, count in sorted(kinds.items()))
        judged = []
        unstated = 0
        for key in theirs:
            standing = settled(decisions.get(key, []))
            if standing and standing.get("by") == "human":
                if standing.get("adoption") in ("adopted", "partial", "refused"):
                    judged.append(standing)
                else:
                    unstated += 1
        line = f"{person}: {did}."
        if judged:
            kept = sum(1 for d in judged if d.get("adoption") == "adopted")
            part = sum(1 for d in judged if d.get("adoption") == "partial")
            refused = sum(1 for d in judged if d.get("adoption") == "refused")
            line += f" You judged {len(judged)} of them: kept {kept}"
            if part:
                line += f", kept part of {part}"
            if refused:
                line += f", refused {refused}"
            line += "."
        elif not unstated:
            line += " You have not judged any of them yet."
        if unstated:
            line += (f" {plural(unstated, 'decision')} did not say how the work "
                     f"was received and {verb(unstated, 'is', 'are')} not counted.")
        failed = sum(1 for key in theirs
                     if results.get(key, {}).get("status") not in (None, "ok"))
        if failed:
            line += f" {plural(failed, 'turn')} did not finish."
        lines.append(line)
    return lines


def describe_cost(dispatches, results):
    lines = []
    for person in sorted({record["participant"] for record in dispatches.values()}):
        keys = [key for key, record in dispatches.items() if record["participant"] == person]
        seconds = [results[key]["seconds"] for key in keys
                   if key in results and results[key].get("seconds") is not None]
        tokens = [results[key]["tokens"] for key in keys
                  if key in results and results[key].get("tokens") is not None]
        if seconds:
            line = f"{person}: {statistics.median(seconds):.0f}s per turn, typically."
        else:
            line = f"{person}: no turn reported how long it took."
        if tokens:
            line += (f" {sum(tokens):,} tokens across {plural(len(tokens), 'turn')}"
                     f" that reported.")
            if len(tokens) < len(keys):
                line += f" {len(keys) - len(tokens)} did not report."
        else:
            line += " No turn reported its tokens."
        lines.append(line)
    return lines


def describe_confound(dispatches):
    """The warning that matters most. If each participant only ever did one kind of
    work, the numbers above compare the jobs and not the agents, and they will look
    convincing anyway."""
    by_person = {}
    for record in dispatches.values():
        by_person.setdefault(record["participant"], set()).add(record["kind"])
    if len(by_person) < 2:
        return []
    doers = {}
    for kinds in by_person.values():
        for kind in kinds:
            doers[kind] = doers.get(kind, 0) + 1
    if any(count > 1 for count in doers.values()):
        return []
    described = " and ".join(
        f"{person} has only ever done {', '.join(sorted(kinds))}"
        for person, kinds in sorted(by_person.items())
    )
    return [f"{described}. Until the same kind of work goes to more than one "
            "participant, these numbers compare the jobs rather than the agents."]


def describe_gaps(dispatches, results, decisions, skipped):
    lines = []
    missing = [key for key in dispatches if key not in results]
    if missing:
        lines.append(f"{plural(len(missing), 'dispatch')} "
                     f"{verb(len(missing), 'has', 'have')} no result. "
                     "That is a gap, not work that was never sent.")
    waiting = [key for key in dispatches
               if key in results and not settled(decisions.get(key, []))]
    if waiting:
        lines.append(f"{plural(len(waiting), 'dispatch')} "
                     f"{verb(len(waiting), 'is', 'are')} waiting on your decision. "
                     "Nothing can be learned from those until you judge them.")
    builder_only = [key for key in dispatches
                    if (settled(decisions.get(key, [])) or {}).get("by") == "builder"]
    if builder_only:
        lines.append(f"{plural(len(builder_only), 'decision')} "
                     f"{verb(len(builder_only), 'was', 'were')} made by the builder "
                     "rather than by you, and not counted above.")
    if skipped:
        lines.append(f"{plural(skipped, 'line')} could not be read and "
                     f"{verb(skipped, 'was', 'were')} skipped.")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=None)
    arguments = parser.parse_args(argv)
    path = (arguments.file or Path(__file__).resolve().parent / "training.jsonl").expanduser()
    if not path.exists():
        sys.exit(f"report: no {path}. Run collect.py first.")
    dispatches, results, decisions, skipped = load(path)
    if not dispatches:
        print(f"{path.name} holds no dispatches yet.")
        return 0
    projects = {key[0] for key in dispatches}
    tasks = {(record.get("project"), record.get("task_id")) for record in dispatches.values()}
    print(f"{plural(len(dispatches), 'dispatch')} across "
          f"{plural(len(tasks), 'task')} in {plural(len(projects), 'project')}.")
    for group in (describe_work(dispatches, results, decisions),
                  describe_cost(dispatches, results),
                  describe_confound(dispatches),
                  describe_gaps(dispatches, results, decisions, skipped)):
        if group:
            print()
            for line in group:
                print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
