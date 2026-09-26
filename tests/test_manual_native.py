import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from todo_flow.manual_native import import_result, prepare
from todo_flow.store import Store


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class ManualNativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state, self.vault, self.artifacts = (self.root / x for x in ("state", "vault", "artifacts"))
        self.vault.mkdir()
        self.artifacts.mkdir()
        source_dir = self.artifacts / "fresh-input"
        source_dir.mkdir()
        self.source = source_dir / "source.md"
        self.source.write_text("Source value: 42.\n", encoding="utf-8")
        self.skill = self.root / "skill.md"
        self.skill.write_text("Frozen skill.\n", encoding="utf-8")
        self.contract = self.artifacts / "contract.md"
        self.contract.write_text("Read-only test contract.\n", encoding="utf-8")
        self.sources = write_json(self.artifacts / "sources.json", [
            {"snapshot": str(self.source), "sha256": sha(self.source)}
        ])
        self.skills = write_json(self.artifacts / "skills.json", {
            "schema": "knowledge-skill-source-freeze/v1", "frozen": True,
            "files": [{"path": str(self.skill), "sha256": sha(self.skill)}],
        })
        self.store = Store(self.state)
        self.store.configure({
            "repo": str(self.vault), "github": None, "base": "main",
            "verify": ["python3", "-c", "pass"],
            "worker": {"type": "command", "argv": ["/usr/bin/false"]},
            "writable_patterns": ["1.wiki/*.md"], "context_patterns": [],
            "endpoint": "review", "allow_land": False, "worker_timeout": 600,
            "verify_timeout": 180, "language": "ko", "schema_version": 1,
            "worker_protocol": 2, "worker_launcher": "auto", "created_by": "0.0.1",
            "min_engine_version": "0.0.1",
        })
        self.store.register({
            "id": "native-check", "title": "Native check", "goal": "Validate current page",
            "scope": "Read only", "evidence": "Frozen manifests",
            "conditions": [{"id": "page", "text": "Read existing page", "method": "readback"}],
            "language": "ko",
        })
        self.store.control("native-check", "pause")
        self.backup = self.root / "before-state"
        claimed = prepare(self.state, "native-check", "Read existing page and report", self.contract,
                          self.sources, self.skills, ["retry-report.md", "retry-evidence.json"],
                          self.backup, owner="native-retry")
        self.request = claimed["request"]
        self.request_path = Path(claimed["request_path"])

    def tearDown(self):
        self.tmp.cleanup()

    def make_result(self, wrong_identity=False, bad_hash=False):
        outputs = []
        for name in self.request["outputs"]:
            path = self.artifacts / name
            path.write_text("Actual bounded readback evidence.\n", encoding="utf-8")
            outputs.append({"name": name, "path": str(path), "sha256": sha(path)})
        if bad_hash:
            outputs[0]["sha256"] = "0" * 64
        out = self.artifacts / "manual-native-result.json"
        write_json(out, {
            "schema": "todo-flow.manual-native-result/v1",
            "todo": {"request_id": "wrong" if wrong_identity else self.request["request_id"],
                     "task_id": self.request["task_id"], "attempt_id": self.request["attempt_id"],
                     "request_sha256": sha(self.request_path)},
            "outputs": outputs,
            "todo_result": {"summary": "Inspected current page and supporting notes.",
                            "verdict": "met", "conditions": [
                                {"id": "page", "verdict": "met", "evidence": "retry-report.md records current hashes"}
                            ]},
        })
        return out

    def task(self):
        return next(row for row in self.store.snapshot()["tasks"] if row["id"] == self.request["task_id"])

    def test_claim_import_binds_actual_outputs_and_finishes_atomically(self):
        self.assertTrue(self.backup.is_dir())
        self.assertEqual(self.request["execution_mode"], "native")
        self.assertIsNone(self.request["orca_evidence"])
        self.assertEqual(self.task()["status"], "running")
        result_path = self.make_result()
        imported = import_result(self.state, self.request_path, result_path)
        snapshot = self.store.snapshot()
        self.assertEqual(self.task()["status"], "done")
        self.assertEqual(len(snapshot["results"]), 1)
        self.assertEqual(snapshot["attempts"][0]["status"], "finished")
        self.assertEqual(self.store.track("native-check")["control"], "paused")
        stored = json.loads(snapshot["results"][0]["body"])
        self.assertEqual(stored["manual_execution"]["mode"], "native")
        self.assertEqual(stored["manual_execution"]["request_sha256"], sha(self.request_path))
        self.assertEqual(imported["task_id"], self.request["task_id"])

    def test_wrong_request_identity_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "does not bind the current native"):
            import_result(self.state, self.request_path, self.make_result(wrong_identity=True))
        self.assertEqual(self.task()["status"], "running")
        self.assertEqual(self.store.snapshot()["results"], [])

    def test_wrong_output_hash_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "output name/path/hash mismatch"):
            import_result(self.state, self.request_path, self.make_result(bad_hash=True))
        self.assertEqual(self.task()["status"], "running")
        self.assertEqual(self.store.snapshot()["results"], [])

    def test_changed_frozen_skill_fails_closed(self):
        self.skill.write_text("Changed after claim.\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Skill source hash changed"):
            import_result(self.state, self.request_path, self.make_result())
        self.assertEqual(self.task()["status"], "running")
        self.assertEqual(self.store.snapshot()["results"], [])


if __name__ == "__main__":
    unittest.main()
