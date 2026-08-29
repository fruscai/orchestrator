import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
PROGRAM = PROJECT / "duel.py"
WRITER = PROJECT.parent / "routelog.py"
# A run that used up its rounds with findings still open. Distinct from success so
# nothing downstream reads "ran out of rounds" as "the work is finished".
UNRESOLVED = 3


def quoted(value):
    import shlex

    return shlex.quote(value)


def require_writer(test):
    if not WRITER.is_file():
        test.skipTest(f"no routelog.py at {WRITER}")


def base_command(root, fake, comms, rounds=1, task_id="task-under-test"):
    command_a = f"{quoted(sys.executable)} {quoted(str(fake))} a"
    command_b = f"{quoted(sys.executable)} {quoted(str(fake))} b"
    arguments = [
        sys.executable,
        str(PROGRAM),
        "test task",
        "--agent-a",
        command_a,
        "--agent-b",
        command_b,
        "--builder",
        "a",
        "--review-areas",
        "behavior and output",
        "--rounds",
        str(rounds),
        "--workdir",
        str(root),
        "--comms",
        str(comms),
        "--task-id",
        task_id,
    ]
    for number in range(1, rounds + 1):
        arguments.extend(("--round-title", f"test round {number}"))
    return arguments


class DuelTests(unittest.TestCase):
    def setUp(self):
        require_writer(self)

    def make_fake(self, root):
        fake = root / "fake.py"
        fake.write_text(
            "import sys\n"
            "prompt = sys.stdin.read()\n"
            "print(sys.argv[1] + ':' + prompt.splitlines()[0] + '\\nRound 1, quoted output')\n",
            encoding="utf-8",
        )
        return fake

    def test_round_writes_required_comms_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = self.make_fake(root)
            comms = root / "COMMS.md"
            result = subprocess.run(
                base_command(root, fake, comms), text=True, capture_output=True, check=False
            )
            self.assertEqual(result.returncode, UNRESOLVED, result.stderr)
            text = comms.read_text(encoding="utf-8")
            self.assertRegex(text, r"^## \d{2}-\d{2}-\d{4}\n\nRound 1 — test round 1")
            self.assertRegex(text, r"\n\d{2}:\d{2}\n\nAgent A to Agent B\n\n```")
            self.assertLess(text.index("Agent A to Agent B"), text.index("Agent B to Agent A"))
            self.assertLess(text.index("Agent B to Agent A"), text.index("Agent A to itself"))
            self.assertIn("b:Task:", text)
            self.assertIn("a:Task:", text)

    def test_round_numbers_continue_across_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = self.make_fake(root)
            comms = root / "COMMS.md"
            first = subprocess.run(
                base_command(root, fake, comms), text=True, capture_output=True, check=False
            )
            second = subprocess.run(
                base_command(root, fake, comms), text=True, capture_output=True, check=False
            )
            self.assertEqual(first.returncode, UNRESOLVED, first.stderr)
            self.assertEqual(second.returncode, UNRESOLVED, second.stderr)
            text = comms.read_text(encoding="utf-8")
            self.assertEqual(text.count("## "), 1)
            self.assertIn("Round 1 —", text)
            self.assertIn("Round 2 —", text)

    def test_command_placeholders_use_argument_and_output_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "argument.py"
            fake.write_text(
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[2]).write_text('arg:' + sys.argv[1])\n",
                encoding="utf-8",
            )
            command = f"{quoted(sys.executable)} {quoted(str(fake))} '{{prompt}}' '{{output}}'"
            comms = root / "COMMS.md"
            arguments = [
                sys.executable,
                str(PROGRAM),
                "task",
                "--agent-a",
                command,
                "--agent-b",
                command,
                "--builder",
                "a",
                "--review-areas",
                "output",
                "--round-title",
                "placeholder test",
                "--workdir",
                str(root),
                "--comms",
                str(comms),
                "--task-id",
                "task-under-test",
            ]
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, UNRESOLVED, result.stderr)
            self.assertIn("arg:Task:", comms.read_text(encoding="utf-8"))

    def test_nested_launch_is_refused(self):
        environment = os.environ.copy()
        environment["DUEL_COORDINATOR_ACTIVE"] = "1"
        result = subprocess.run(
            [sys.executable, str(PROGRAM), "task"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("nested coordinator launch refused", result.stderr)

    def test_round_limit_is_enforced(self):
        result = subprocess.run(
            [
                sys.executable,
                str(PROGRAM),
                "task",
                "--agent-a",
                "a",
                "--agent-b",
                "b",
                "--builder",
                "a",
                "--review-areas",
                "output",
                "--round-title",
                "one",
                "--rounds",
                "11",
                "--task-id",
                "task-under-test",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("rounds must be between 1 and 10", result.stderr)

    def test_timeout_kills_descendant_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_pid = root / "child.pid"
            fake = root / "slow.py"
            fake.write_text(
                "import pathlib, subprocess, sys, time\n"
                "child = subprocess.Popen(['/bin/sleep', '30'])\n"
                "pathlib.Path(sys.argv[2]).write_text(str(child.pid))\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            command = f"{quoted(sys.executable)} {quoted(str(fake))} a {quoted(str(child_pid))}"
            arguments = base_command(root, fake, root / "COMMS.md")
            arguments[arguments.index("--agent-a") + 1] = command
            arguments.extend(("--timeout", "1"))
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 1)
            pid = int(child_pid.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_interrupt_kills_active_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent_pid = root / "agent.pid"
            fake = root / "slow.py"
            fake.write_text(
                "import os, pathlib, sys, time\n"
                "pathlib.Path(sys.argv[2]).write_text(str(os.getpid()))\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            command = f"{quoted(sys.executable)} {quoted(str(fake))} a {quoted(str(agent_pid))}"
            arguments = base_command(root, fake, root / "COMMS.md")
            arguments[arguments.index("--agent-a") + 1] = command
            process = subprocess.Popen(
                arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            deadline = time.monotonic() + 3
            while not agent_pid.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(agent_pid.exists())
            process.send_signal(signal.SIGINT)
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, 130)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(agent_pid.read_text(encoding="utf-8")), 0)


class RoutingTests(unittest.TestCase):
    """The routing log is only worth having if it is written every time, including
    when the dispatch fails. A gap in it reads as work that was never sent."""

    def setUp(self):
        require_writer(self)

    def prepare(self, root):
        import shutil

        shutil.copy(WRITER, root / "routelog.py")
        return root / "routing.jsonl"

    def events(self, path):
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def make_fake(self, root, reviewer_reply=None):
        fake = root / "fake.py"
        reply = repr(reviewer_reply) if reviewer_reply else "None"
        fake.write_text(
            "import sys\n"
            "prompt = sys.stdin.read()\n"
            f"reply = {reply}\n"
            "if reply is not None and sys.argv[1] == 'b':\n"
            "    print(reply)\n"
            "else:\n"
            "    print(sys.argv[1] + ':' + prompt.splitlines()[0] + '\\nRound 1, quoted output')\n",
            encoding="utf-8",
        )
        return fake

    def test_round_records_three_dispatches_each_with_a_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = self.prepare(root)
            fake = self.make_fake(root)
            arguments = base_command(root, fake, root / "COMMS.md")
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, UNRESOLVED, result.stderr)
            events = self.events(log)
            dispatches = [e for e in events if e["event"] == "dispatch"]
            results = [e for e in events if e["event"] == "result"]
            self.assertEqual([e["kind"] for e in dispatches], ["build", "review", "fix"])
            self.assertEqual([e["seq"] for e in dispatches], [1, 2, 3])
            self.assertEqual([e["role"] for e in dispatches], ["builder", "reviewer", "builder"])
            self.assertEqual({e["id"] for e in results}, {e["id"] for e in dispatches})
            self.assertTrue(all(e["status"] == "ok" for e in results))
            # The review answers the build, and the fix answers the review.
            self.assertIsNone(dispatches[0]["parent"])
            self.assertEqual(dispatches[1]["parent"], dispatches[0]["id"])
            self.assertEqual(dispatches[2]["parent"], dispatches[1]["id"])
            # The task recorded is the prompt that was sent, not a summary of it.
            self.assertIn("You are Agent B, the read-only reviewer", dispatches[1]["task"])

    def test_timeout_still_records_a_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = self.prepare(root)
            fake = root / "slow.py"
            fake.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            command = f"{quoted(sys.executable)} {quoted(str(fake))} a"
            arguments = base_command(root, fake, root / "COMMS.md")
            arguments[arguments.index("--agent-a") + 1] = command
            arguments.extend(("--timeout", "1"))
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 1)
            events = self.events(log)
            self.assertEqual(len([e for e in events if e["event"] == "dispatch"]), 1)
            ended = [e for e in events if e["event"] == "result"]
            self.assertEqual(len(ended), 1)
            self.assertEqual(ended[0]["status"], "timeout")
            self.assertIn("timed out", ended[0]["error"])

    def test_interrupt_still_records_a_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = self.prepare(root)
            started = root / "agent.pid"
            fake = root / "slow.py"
            fake.write_text(
                "import os, pathlib, sys, time\n"
                "pathlib.Path(sys.argv[2]).write_text(str(os.getpid()))\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            command = f"{quoted(sys.executable)} {quoted(str(fake))} a {quoted(str(started))}"
            arguments = base_command(root, fake, root / "COMMS.md")
            arguments[arguments.index("--agent-a") + 1] = command
            process = subprocess.Popen(
                arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(started.exists())
            process.send_signal(signal.SIGINT)
            process.communicate(timeout=10)
            self.assertEqual(process.returncode, 130)
            ended = [e for e in self.events(log) if e["event"] == "result"]
            self.assertEqual(len(ended), 1)
            self.assertEqual(ended[0]["status"], "interrupted")

    def test_no_findings_stops_before_the_rounds_asked_for(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = self.prepare(root)
            fake = self.make_fake(root, reviewer_reply="NO FINDINGS")
            arguments = base_command(root, fake, root / "COMMS.md", rounds=3)
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            events = self.events(log)
            dispatches = [e for e in events if e["event"] == "dispatch"]
            # One round, and no builder turn spent disposing of nothing.
            self.assertEqual([e["kind"] for e in dispatches], ["build", "review"])
            review = [e for e in events if e["event"] == "result"][1]
            self.assertEqual(review["findings"], 0)
            self.assertNotIn("Round 2 —", (root / "COMMS.md").read_text(encoding="utf-8"))

    def test_a_task_id_with_no_writer_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = self.make_fake(root)
            arguments = base_command(root, fake, root / "COMMS.md")
            arguments.extend(("--routelog", str(root / "absent.py")))
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            # Running unlogged would leave exactly the gap the log exists to prevent.
            self.assertEqual(result.returncode, 2)
            self.assertIn("no routelog.py found", result.stderr)

    def test_omitting_task_id_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = self.make_fake(root)
            arguments = base_command(root, fake, root / "COMMS.md")
            index = arguments.index("--task-id")
            del arguments[index:index + 2]
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            # There is no unlogged mode: a run without a task id cannot be recorded.
            self.assertEqual(result.returncode, 2)
            self.assertIn("--task-id", result.stderr)

    def test_reviewer_timeout_still_records_every_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = self.prepare(root)
            fake = root / "fake.py"
            fake.write_text(
                "import sys, time\n"
                "if sys.argv[1] == 'b':\n"
                "    time.sleep(30)\n"
                "prompt = sys.stdin.read()\n"
                "print(sys.argv[1] + ':' + prompt.splitlines()[0])\n",
                encoding="utf-8",
            )
            arguments = base_command(root, fake, root / "COMMS.md")
            arguments.extend(("--timeout", "2"))
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 1)
            events = self.events(log)
            dispatches = [e for e in events if e["event"] == "dispatch"]
            self.assertEqual([e["kind"] for e in dispatches], ["build", "review"])
            ended = {e["id"]: e for e in events if e["event"] == "result"}
            self.assertEqual(ended[dispatches[0]["id"]]["status"], "ok")
            self.assertEqual(ended[dispatches[1]["id"]]["status"], "timeout")

    def test_interrupt_during_dispatch_still_records_a_result(self):
        # A SIGINT that lands after the dispatch record and before the agent starts
        # must still leave a result. The stub writer interrupts the coordinator from
        # inside the dispatch itself, which is exactly that window.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = self.prepare(root)
            fake = root / "slow.py"
            fake.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            stub = root / "stub.py"
            stub.write_text(
                "import os, signal, subprocess, sys\n"
                "if 'dispatch' in sys.argv:\n"
                "    os.kill(os.getppid(), signal.SIGINT)\n"
                f"real = {str(root / 'routelog.py')!r}\n"
                "raise SystemExit(subprocess.run([sys.executable, real] + sys.argv[1:]).returncode)\n",
                encoding="utf-8",
            )
            arguments = base_command(root, fake, root / "COMMS.md")
            arguments.extend(("--routelog", str(stub), "--timeout", "5"))
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 130, result.stderr)
            events = self.events(log)
            self.assertEqual(len([e for e in events if e["event"] == "dispatch"]), 1)
            ended = [e for e in events if e["event"] == "result"]
            self.assertEqual(len(ended), 1)
            self.assertEqual(ended[0]["status"], "interrupted")

    def test_an_inexact_sentinel_does_not_stop_the_rounds(self):
        # The prompt demands exactly NO FINDINGS and nothing else. Anything looser is
        # a contradiction, and a contradiction must not record zero findings.
        for reply in ("NO FINDINGS.", "No findings", "NO FINDINGS\n- one real defect after all"):
            with self.subTest(reply=reply), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                log = self.prepare(root)
                fake = self.make_fake(root, reviewer_reply=reply)
                arguments = base_command(root, fake, root / "COMMS.md")
                result = subprocess.run(arguments, text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, UNRESOLVED, result.stderr)
                events = self.events(log)
                dispatches = [e for e in events if e["event"] == "dispatch"]
                self.assertEqual([e["kind"] for e in dispatches], ["build", "review", "fix"])
                review = [e for e in events if e["event"] == "result"][1]
                self.assertNotEqual(review.get("findings"), 0)

    def test_elapsed_carries_across_separate_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = self.prepare(root)
            fake = self.make_fake(root)
            arguments = base_command(root, fake, root / "COMMS.md")
            subprocess.run(arguments, text=True, capture_output=True, check=False)
            subprocess.run(arguments, text=True, capture_output=True, check=False)
            dispatches = [e for e in self.events(log) if e["event"] == "dispatch"]
            self.assertEqual(len(dispatches), 6)
            self.assertEqual(dispatches[0]["elapsed_so_far"], 0.0)
            self.assertGreater(dispatches[3]["elapsed_so_far"], 0.0)
            self.assertEqual(dispatches[3]["rounds_so_far"], 1)


class PromptTests(unittest.TestCase):
    def setUp(self):
        require_writer(self)

    def test_proposal_carries_only_the_last_disposition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seen = root / "prompts.txt"
            fake = root / "fake.py"
            fake.write_text(
                "import pathlib, sys\n"
                "prompt = sys.stdin.read()\n"
                "pathlib.Path(sys.argv[2]).open('a').write(prompt + '\\n=====\\n')\n"
                "print(sys.argv[1] + ' round marker ' + str(len(prompt)))\n",
                encoding="utf-8",
            )
            command_a = f"{quoted(sys.executable)} {quoted(str(fake))} a {quoted(str(seen))}"
            command_b = f"{quoted(sys.executable)} {quoted(str(fake))} b {quoted(str(seen))}"
            arguments = base_command(root, fake, root / "COMMS.md", rounds=3)
            arguments[arguments.index("--agent-a") + 1] = command_a
            arguments[arguments.index("--agent-b") + 1] = command_b
            subprocess.run(arguments, text=True, capture_output=True, check=False)
            prompts = seen.read_text(encoding="utf-8").split("=====")
            proposals = [p for p in prompts if "Prior dispositions:" in p]
            self.assertEqual(len(proposals), 3)
            # Round 3 sees round 2's disposition and not round 1's, so the cost of a
            # round does not climb with the rounds before it.
            self.assertIn("Prior dispositions:\nNo prior rounds.", proposals[0])
            self.assertEqual(proposals[2].count("a round marker"), 1)


class TokenTests(unittest.TestCase):
    """Cost per round is only trustworthy if an agent that reports nothing is recorded
    as reporting nothing, rather than as costing nothing."""

    def setUp(self):
        if not WRITER.is_file():
            self.skipTest(f"no routelog.py at {WRITER}")

    def test_tokens_written_to_the_placeholder_are_recorded(self):
        import shutil

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy(WRITER, root / "routelog.py")
            log = root / "routing.jsonl"
            fake = root / "fake.py"
            # Only the reviewer reports, so the run has to hold both cases at once.
            fake.write_text(
                "import pathlib, sys\n"
                "prompt = sys.stdin.read()\n"
                "if sys.argv[1] == 'b':\n"
                "    pathlib.Path(sys.argv[2]).write_text('8,892')\n"
                "print(sys.argv[1] + ':' + prompt.splitlines()[0])\n",
                encoding="utf-8",
            )
            command_a = f"{quoted(sys.executable)} {quoted(str(fake))} a '{{tokens}}'"
            command_b = f"{quoted(sys.executable)} {quoted(str(fake))} b '{{tokens}}'"
            arguments = base_command(root, fake, root / "COMMS.md")
            arguments[arguments.index("--agent-a") + 1] = command_a
            arguments[arguments.index("--agent-b") + 1] = command_b
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, UNRESOLVED, result.stderr)
            results = [
                json.loads(line)
                for line in log.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line)["event"] == "result"
            ]
            # Comma separators are what the tools actually print.
            self.assertEqual([r["tokens"] for r in results], [None, 8892, None])
            self.assertIn("Agent B 8,892", result.stdout)
            self.assertIn("not reported by Agent A", result.stdout)


class SeverityTests(unittest.TestCase):
    """The smallest thing that works is what is being built, so an improvement must not
    hold a round open and a security finding must never be left behind."""

    def setUp(self):
        if not WRITER.is_file():
            self.skipTest(f"no routelog.py at {WRITER}")

    def run_with_review(self, root, reply, rounds=3):
        import shutil

        shutil.copy(WRITER, root / "routelog.py")
        fake = root / "fake.py"
        fake.write_text(
            "import sys\n"
            "prompt = sys.stdin.read()\n"
            f"reply = {reply!r}\n"
            "if sys.argv[1] == 'b':\n"
            "    print(reply)\n"
            "else:\n"
            "    print(sys.argv[1] + ':' + prompt.splitlines()[0])\n",
            encoding="utf-8",
        )
        arguments = base_command(root, fake, root / "COMMS.md", rounds=rounds)
        return subprocess.run(arguments, text=True, capture_output=True, check=False)

    def findings_recorded(self, root):
        events = [
            json.loads(line)
            for line in (root / "routing.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return [e["findings"] for e in events if e["event"] == "result"]

    def test_only_improvements_is_shippable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_with_review(root, "- [IMPROVEMENT] the naming could be clearer")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("smallest thing that works", result.stdout)
            # A round that shipped with an improvement open must not claim the reviewer
            # found nothing.
            self.assertIn("deliberately not acted on",
                          (root / "COMMS.md").read_text(encoding="utf-8"))
            self.assertNotIn("Round 2 —", (root / "COMMS.md").read_text(encoding="utf-8"))
            self.assertEqual(self.findings_recorded(root)[1], 1)

    def test_blocking_keeps_the_rounds_going(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_with_review(root, "- [BLOCKING] it crashes on an empty file")
            self.assertEqual(result.returncode, UNRESOLVED, result.stderr)
            self.assertIn("Round 3 —", (root / "COMMS.md").read_text(encoding="utf-8"))

    def test_security_is_never_left_behind(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Tagged as otherwise shippable on purpose: security must outrank that.
            result = self.run_with_review(
                root, "- [SECURITY] the token is written to a world readable path", rounds=1
            )
            self.assertEqual(result.returncode, 4)
            self.assertIn("checked it yourself", result.stderr)

    def test_an_untagged_review_is_not_shippable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # A reviewer ignoring the format must not read as nothing to fix.
            result = self.run_with_review(root, "- the naming could be clearer")
            self.assertEqual(result.returncode, UNRESOLVED, result.stderr)
            self.assertIsNone(self.findings_recorded(root)[1])

    def test_questions_are_put_in_front_of_the_human(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_with_review(
                root,
                "- [IMPROVEMENT] minor\n[QUESTION] should this refuse unknown hosts outright?",
            )
            self.assertIn("The agents need a decision from you:", result.stdout)
            self.assertIn("should this refuse unknown hosts outright?", result.stdout)
            # A question stops the run: the rounds after it would rest on an answer
            # nobody gave.
            self.assertEqual(result.returncode, 5)
            text = (root / "COMMS.md").read_text(encoding="utf-8")
            self.assertNotIn("Round 2 —", text)
            # In the round itself, under a heading of its own. Printing it to a terminal
            # that gets closed is not a record.
            self.assertIn("questions for you", text)
            self.assertIn("1. should this refuse unknown hosts outright?", text)
            self.assertLess(text.index("Agent A to itself"), text.index("questions for you"))

    def test_a_round_with_no_questions_has_no_section(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_with_review(root, "- [IMPROVEMENT] the naming could be clearer")
            self.assertNotIn("questions for you", (root / "COMMS.md").read_text(encoding="utf-8"))

    def test_a_tagged_improvement_does_not_launder_an_untagged_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # The untagged line could be the finding that mattered, so the round
            # stays open rather than shipping on the one readable tag.
            result = self.run_with_review(
                root, "- [IMPROVEMENT] minor\n- it crashes on an empty file", rounds=1
            )
            self.assertEqual(result.returncode, UNRESOLVED, result.stderr)
            self.assertNotIn("smallest thing that works", result.stdout)
            self.assertIn("1 line(s) the reviewer did not tag", result.stdout)

    def test_security_survives_a_later_failure(self):
        import shutil

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy(WRITER, root / "routelog.py")
            calls = root / "builder.calls"
            fake = root / "fake.py"
            # The reviewer raises security every round; the builder's third call is
            # the round 2 proposal, which fails. The failure must not eat the flag.
            fake.write_text(
                "import pathlib, sys\n"
                "prompt = sys.stdin.read()\n"
                "if sys.argv[1] == 'b':\n"
                "    print('- [SECURITY] the token is written to a world readable path')\n"
                "    raise SystemExit(0)\n"
                f"counter = pathlib.Path({str(calls)!r})\n"
                "count = int(counter.read_text()) + 1 if counter.exists() else 1\n"
                "counter.write_text(str(count))\n"
                "if count >= 3:\n"
                "    raise SystemExit(9)\n"
                "print('a:' + prompt.splitlines()[0])\n",
                encoding="utf-8",
            )
            arguments = base_command(root, fake, root / "COMMS.md", rounds=2)
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertIn("checked it yourself", result.stderr)
            self.assertIn("agent exited with 9", result.stderr)

    def test_a_proposal_question_survives_a_reviewer_failure(self):
        import shutil

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy(WRITER, root / "routelog.py")
            fake = root / "fake.py"
            # The builder asks in its proposal, then the reviewer dies. The question
            # was already asked, and an error does not unask it.
            fake.write_text(
                "import sys\n"
                "prompt = sys.stdin.read()\n"
                "if sys.argv[1] == 'b':\n"
                "    raise SystemExit(9)\n"
                "print('proposal\\n[QUESTION] should unknown hosts be refused outright?')\n",
                encoding="utf-8",
            )
            arguments = base_command(root, fake, root / "COMMS.md")
            result = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 5, result.stderr)
            self.assertIn("should unknown hosts be refused outright?", result.stdout)
            self.assertIn("agent exited with 9", result.stderr)


class AnswerTests(unittest.TestCase):
    """A question is only in the loop if the answer gets back into it. Answering by hand
    and retyping it into the next task is the step that quietly does not happen."""

    ANSWER = PROJECT.parent / "answer.py"

    def setUp(self):
        if not WRITER.is_file():
            self.skipTest(f"no routelog.py at {WRITER}")
        if not self.ANSWER.is_file():
            self.skipTest(f"no answer.py at {self.ANSWER}")

    def build(self, root):
        import shutil

        shutil.copy(WRITER, root / "routelog.py")
        fake = root / "fake.py"
        fake.write_text(
            "import pathlib, sys\n"
            "prompt = sys.stdin.read()\n"
            "pathlib.Path(sys.argv[2]).open('a').write(prompt + '\\n=====\\n')\n"
            "if sys.argv[1] == 'b':\n"
            "    print('- [BLOCKING] it drops the last row\\n"
            "[QUESTION] should empty files be an error?')\n"
            "else:\n"
            "    print(sys.argv[1] + ': built')\n",
            encoding="utf-8",
        )
        seen = root / "prompts.txt"
        arguments = base_command(root, fake, root / "COMMS.md")
        for side in ("--agent-a", "--agent-b"):
            letter = side[-1]
            arguments[arguments.index(side) + 1] = (
                f"{quoted(sys.executable)} {quoted(str(fake))} {letter} {quoted(str(seen))}"
            )
        return arguments, seen

    def answer(self, root, *extra):
        return subprocess.run(
            [sys.executable, str(self.ANSWER), "--comms", str(root / "COMMS.md"), *extra],
            text=True, capture_output=True, check=False,
        )

    def test_an_answer_reaches_the_next_round(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arguments, seen = self.build(root)
            first = subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(first.returncode, 5, first.stderr)
            recorded = self.answer(root, "yes, an empty file is an error")
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            text = (root / "COMMS.md").read_text(encoding="utf-8")
            # Appended, never written back over what was asked.
            self.assertLess(text.index("questions for you"), text.index("answers to round 1"))
            self.assertIn("1. yes, an empty file is an error", text)
            seen.unlink()
            subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertIn("yes, an empty file is an error",
                          seen.read_text(encoding="utf-8").split("=====")[0])

    def test_passthrough_is_recorded_as_a_deliberate_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arguments, _ = self.build(root)
            subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.assertEqual(self.answer(root, "--passthrough").returncode, 0)
            self.assertIn("1. Passthrough", (root / "COMMS.md").read_text(encoding="utf-8"))

    def test_an_unanswered_question_is_refused_without_passthrough(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arguments, _ = self.build(root)
            subprocess.run(arguments, text=True, capture_output=True, check=False)
            refused = self.answer(root)
            self.assertEqual(refused.returncode, 1)
            self.assertIn("left on purpose", refused.stderr)

    def test_answers_are_never_written_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arguments, _ = self.build(root)
            subprocess.run(arguments, text=True, capture_output=True, check=False)
            self.answer(root, "--passthrough")
            again = self.answer(root, "--passthrough")
            self.assertEqual(again.returncode, 1)
            self.assertIn("already has answers", again.stderr)


if __name__ == "__main__":
    unittest.main()
