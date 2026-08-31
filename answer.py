"""Record answers to the questions a round asked, into COMMS.md.

A question stops the run, so the answers are always written before the next round
starts and appending them keeps the file in order. They are appended as their own block
rather than written back over the questions: the record of what was asked stays exactly
as it was asked.

    python3 answer.py "yes, security outranks the interrupt" --passthrough

An answer of Passthrough means the question was put and left unanswered on purpose.
That is not the same as never having been asked, and the next round is told the
difference. Every question gets a line, so a partial reply cannot silently drop one.
"""

import argparse
import os
import re
import sys
from pathlib import Path

PASSTHROUGH = "Passthrough"


def last_round_with_questions(text):
    """The last round that asked something, and whether it was already answered.

    Only the last one: a question stops the run, so an earlier unanswered round means
    the file was written by hand and this should not guess which one is meant.
    """
    rounds = list(re.finditer(r"^Round (\d+) — .+$", text, re.MULTILINE))
    if not rounds:
        return None, [], False
    for match in reversed(rounds):
        start = match.end()
        end = len(text)
        for later in rounds:
            if later.start() > match.start():
                end = later.start()
                break
        body = text[start:end]
        found = re.search(r"^questions for you\n\n((?:\d+\. .+\n)+)", body, re.MULTILINE)
        if found:
            questions = [line.split(". ", 1)[1].strip()
                         for line in found.group(1).strip().splitlines()]
            answered = bool(re.search(r"^answers to round \d+$", body, re.MULTILINE))
            return int(match.group(1)), questions, answered
    return None, [], False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("answers", nargs="*",
                        help="one per question, in the order they were asked")
    parser.add_argument("--comms", type=Path, default=Path("COMMS.md"))
    parser.add_argument("--passthrough", action="store_true",
                        help="fill every remaining question with Passthrough")
    arguments = parser.parse_args(argv)
    path = arguments.comms.expanduser()
    if not path.exists():
        sys.exit(f"answer: no {path}")
    text = path.read_text(encoding="utf-8")
    number, questions, answered = last_round_with_questions(text)
    if number is None:
        sys.exit("answer: no round in this file asked anything")
    if answered:
        sys.exit(f"answer: round {number} already has answers. Nothing is ever "
                 "overwritten here, so there is nothing to add")
    given = list(arguments.answers)
    if len(given) > len(questions):
        sys.exit(f"answer: round {number} asked {len(questions)} question(s) and "
                 f"{len(given)} were given")
    if len(given) < len(questions) and not arguments.passthrough:
        missing = len(questions) - len(given)
        sys.exit(f"answer: {missing} question(s) unanswered. Answer them, or pass "
                 "--passthrough to record that they were left on purpose")
    given += [PASSTHROUGH] * (len(questions) - len(given))
    block = f"\nanswers to round {number}\n\n"
    block += "".join(f"{index}. {value.strip() or PASSTHROUGH}\n"
                     for index, value in enumerate(given, 1))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(block)
        handle.flush()
        os.fsync(handle.fileno())
    for index, (question, value) in enumerate(zip(questions, given), 1):
        print(f"{index}. {question}\n   {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
