"""Gather every project's routing log into one training log.

The project logs are the record. This reads them and writes `training.jsonl`, which is
a build product and never authored by hand: if it is ever wrong you delete it and run
this again. That is also why skipping a run costs nothing. It rebuilds from the
projects every time, so there is no moment you can miss and no state to fall behind.

    python3 collect.py

Each record gains the project it came from. Nothing else is altered, and the projects
are only ever read.
"""

import argparse
import json
import os
import sys
from pathlib import Path

EVENTS = ("dispatch", "result", "decision")


def read_log(path):
    """Every well formed record, in file order, with the count of lines that were not.
    A malformed line is skipped rather than raised on, the same as routelog does, but
    the count is reported: silently dropping records is how a log stops being trusted."""
    records = []
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
            if not isinstance(record, dict) or record.get("event") not in EVENTS:
                skipped += 1
                continue
            records.append(record)
    return records, skipped


def summarise(records):
    """What the project holds, and what is missing from it. A dispatch with no result
    is the gap worth naming: it reads as work that was never sent."""
    dispatches = {r["id"] for r in records if r["event"] == "dispatch" and r.get("id")}
    ended = {r["id"] for r in records if r["event"] == "result"}
    decided = {r["id"] for r in records if r["event"] == "decision"}
    return {
        "dispatches": len(dispatches),
        "results": len(ended),
        "decisions": len(decided),
        "open": len(dispatches - ended),
        "undecided": len(dispatches - decided),
    }


def collect(root, out):
    """Read every project log under root and write them as one file. Written to a
    temporary file and moved into place, so an interrupted run leaves the previous
    training log intact rather than a half written one."""
    # The root keeps its own log for work on the shared scripts. Left out, that work
    # would be written and then never collected, which is the one thing this must not do.
    projects = sorted(
        path for path in root.glob("*/routing.jsonl") if path.is_file()
    )
    if (root / "routing.jsonl").is_file():
        projects.insert(0, root / "routing.jsonl")
    written = 0
    lines = []
    report = []
    for path in projects:
        project = path.parent.name
        records, skipped = read_log(path)
        for record in records:
            # Ids are generated per project, so the pair is what identifies a dispatch
            # once the projects are read together.
            record["project"] = project
            lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False))
            written += 1
        counts = summarise(records)
        counts["project"] = project
        counts["skipped"] = skipped
        counts["read"] = len(records)
        report.append(counts)
    temporary = out.with_suffix(out.suffix + ".partial")
    temporary.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    os.replace(temporary, out)
    return report, written


def verify(out, written):
    """Count what landed. This is the check, so nobody has to read the file."""
    records, skipped = read_log(out)
    return len(records) == written and skipped == 0, len(records)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    # The projects sit beside this repository, not inside it, so the default root is the
    # folder holding them. The training log stays here, with the script that writes it.
    here = Path(__file__).resolve().parent
    parser.add_argument("--root", type=Path, default=here.parent)
    parser.add_argument("--out", type=Path, default=None)
    arguments = parser.parse_args(argv)
    root = arguments.root.expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"collect: {root} is not a directory")
    out = (arguments.out or here / "training.jsonl").expanduser().resolve()
    report, written = collect(root, out)
    if not report:
        print(f"No project routing logs under {root}. Nothing to collect.")
        return 0
    width = max(len(entry["project"]) for entry in report)
    for entry in report:
        line = (f"{entry['project']:<{width}}  {entry['dispatches']} dispatches, "
                f"{entry['results']} results, {entry['decisions']} judged")
        notes = []
        if entry["open"]:
            notes.append(f"{entry['open']} with no result, which is a gap")
        if entry["undecided"]:
            notes.append(f"{entry['undecided']} still waiting on you")
        if entry["skipped"]:
            notes.append(f"{entry['skipped']} unreadable lines skipped")
        print(line + ("  — " + "; ".join(notes) if notes else ""))
    matched, landed = verify(out, written)
    print()
    print(f"Wrote {landed} records to {out.name} from {len(report)} project"
          + ("s" if len(report) != 1 else "") + ".")
    if matched:
        print("Everything in the projects reached the training log.")
        return 0
    print(f"Counts do not match: {written} read from the projects, {landed} landed. "
          "The training log is a build product, so delete it and run this again.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
