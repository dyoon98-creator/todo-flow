import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from todo_flow.manual_orca import bind_completion, import_result, prepare
from todo_flow.store import Store


FIXTURES = Path(__file__).parent / "fixtures"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return Path(path)


class ManualOrcaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.state = root / "todo-state"
        self.vault = root / "vault"
        self.vault.mkdir()
        self.artifacts = root / "artifacts"
        self.artifacts.mkdir()
        source_root = self.artifacts / "fresh-input"
        source_root.mkdir()
        self.source = source_root / "source.md"
        self.source.write_text("Source says 18 applicants.\n", encoding="utf-8")
        self.skill = root / "installed-skill.md"
        self.skill.write_text("Frozen skill instruction.\n", encoding="utf-8")
        self.contract = self.artifacts / "fresh-trial-contract.md"
        self.contract.write_text("Fresh source-to-draft trial.\n", encoding="utf-8")
        self.source_manifest = write_json(
            self.artifacts / "fresh-source-manifest.json",
            [{"snapshot": str(self.source), "sha256": digest(self.source)}],
        )
        self.skill_manifest = write_json(
            self.artifacts / "skill-source-freeze.json",
            {
                "schema": "knowledge-skill-source-freeze/v1",
                "frozen": True,
                "files": [{"path": str(self.skill), "sha256": digest(self.skill)}],
            },
        )
        self.store = Store(self.state)
        self.store.configure(
            {
                "repo": str(self.vault),
                "github": None,
                "base": "main",
                "verify": ["python3", "-c", "pass"],
                "worker": {"type": "command", "argv": ["/usr/bin/false"]},
                "writable_patterns": ["1.wiki/*.md"],
                "context_patterns": [],
                "endpoint": "review",
                "allow_land": False,
                "worker_timeout": 600,
                "verify_timeout": 180,
                "language": "ko",
                "schema_version": 1,
                "worker_protocol": 2,
                "worker_launcher": "auto",
                "created_by": "0.0.1",
                "min_engine_version": "0.0.1",
            }
        )
        self.store.register(
            {
                "id": "manual-trial",
                "title": "Fresh validation",
                "goal": "Validate source claims and draft privately",
                "scope": "No production writes",
                "evidence": "Frozen source manifest",
                "conditions": [
                    {"id": "fresh", "text": "Draft from source", "method": "inspect"}
                ],
                "language": "ko",
            }
        )
        self.store.control("manual-trial", "pause")
        self.backup = root / "todo-state-before-manual"

    def tearDown(self):
        self.temp.cleanup()

    def prepare_request(self):
        prepared = prepare(
            self.state,
            "manual-trial",
            "Run fresh source-to-draft trial",
            self.contract,
            self.source_manifest,
            self.skill_manifest,
            21600,
            self.backup,
        )
        return prepared, prepared["request"], Path(prepared["request_path"])

    def task_row(self, task_id):
        return next(row for row in self.store.snapshot()["tasks"] if row["id"] == task_id)

    def make_worker_outputs(self, request, request_path, *, bind_skill=True):
        wiki = self.artifacts / "fresh-wiki.md"
        wiki.write_text(
            "# 개인 채무조정과 NPL 회수\n\n원문에 근거한 stage draft.\n",
            encoding="utf-8",
        )
        decision = self.artifacts / "fresh-structure-decision.md"
        decision.write_text(
            "기존 구조 보강 여부와 신규 구조 여부를 분리 판정함.\n",
            encoding="utf-8",
        )
        claims = self.artifacts / "fresh-claims.json"
        source_row = request["source_manifest"]["files"][0]
        write_json(
            claims,
            [
                {
                    "output_passage": "원문에 근거한 stage draft",
                    "source_path": source_row["path"],
                    "source_excerpt": "Source says 18 applicants.",
                    "source_line": 1,
                    "source_sha256": source_row["sha256"],
                    "interpretation": "source-reported count",
                }
            ],
        )
        wiki_hash, decision_hash, claims_hash = digest(wiki), digest(decision), digest(claims)
        worker = {
            "todo": {
                "request_id": request["request_id"],
                "task_id": request["task_id"],
                "attempt_id": request["attempt_id"],
                "request_sha256": digest(request_path),
            },
            "source_manifest_sha256": request["source_manifest"]["sha256"],
            "skill_manifest_sha256": (
                request["skill_manifest"]["sha256"] if bind_skill else "0" * 64
            ),
            "outputs": [
                {"name": "fresh-wiki.md", "sha256": wiki_hash},
                {"name": "fresh-structure-decision.md", "sha256": decision_hash},
                {"name": "fresh-claims.json", "sha256": claims_hash},
            ],
            "checks": {
                "path_metadata_link_helper": {
                    "argv": [
                        "python3",
                        "validate_vault_page.py",
                        "--vault-root",
                        str(self.vault),
                    ],
                    "exit_code": 0,
                },
                "repeat_assessment": {
                    "wiki_sha256_before": wiki_hash,
                    "wiki_sha256_after": wiki_hash,
                    "updated_before": "2026-09-26",
                    "updated_after": "2026-09-26",
                },
            },
            "todo_result": {"summary": "Completed fresh source-to-draft validation."},
        }
        run_path = write_json(
            self.artifacts / "fresh-run.json",
            {"schema": "knowledge-flow-fresh-run/v1", "worker_authored": worker},
        )
        return {"wiki": wiki, "decision": decision, "claims": claims, "run": run_path}

    def make_runtime(self, request, request_path, *, startup_only=False, omit_skill_binding=False):
        fixture_name = (
            "orca-startup-bound.recorded.json"
            if startup_only
            else "orca-runtime-completed.recorded.json"
        )
        captured = read_json(FIXTURES / fixture_name)
        runtime_root = self.artifacts / "runtime"
        state_root = runtime_root / "state-root"
        state_dir = state_root / "manual-trial-run"
        state_dir.mkdir(parents=True)
        prompt_text = "\n".join(
            (
                f"request_id={request['request_id']}",
                f"task_id={request['task_id']}",
                f"attempt_id={request['attempt_id']}",
                f"request_sha256={digest(request_path)}",
                f"contract_sha256={request['contract']['sha256']}",
                f"source_manifest_sha256={request['source_manifest']['sha256']}",
                *(
                    ()
                    if omit_skill_binding
                    else (f"skill_manifest_sha256={request['skill_manifest']['sha256']}",)
                ),
            )
        ) + "\n"
        dispatch_instruction = runtime_root / "dispatch-instruction.md"
        dispatch_instruction.write_text(prompt_text, encoding="utf-8")
        startup_prompt = state_dir / "instruction.md"
        startup_prompt.write_text(prompt_text, encoding="utf-8")
        report_path = self.artifacts / "orca-worker-report.md"
        report_path.write_text(
            "Orca worker completed; Main confirms result hashes.\n", encoding="utf-8"
        )
        interactive = copy.deepcopy(captured["interactive"])
        interactive_path = write_json(state_dir / "interactive.json", interactive)
        record_template = copy.deepcopy(captured["record"])
        job = "manual-trial-run"
        record = {
            **record_template,
            "bridge_job": job,
            "job": job,
            "name": job,
            "state_root": str(state_root),
            "state_dir": str(state_dir),
            "instruction": str(dispatch_instruction),
            "instruction_sha256": digest(dispatch_instruction),
            "prompt_sha256": digest(startup_prompt),
            "interactive_status_path": str(interactive_path),
            "report_path": str(report_path),
        }
        if not startup_only:
            interactive["report_sha256"] = digest(report_path)
            write_json(interactive_path, interactive)
        record_path = write_json(self.artifacts / "orca-global-dispatch.json", record)
        return record_path

    def test_prepare_claims_before_dispatch_and_keeps_legacy_worker_disabled(self):
        prepared, request, request_path = self.prepare_request()
        current = self.store.track("manual-trial")
        task = self.task_row(request["task_id"])
        self.assertTrue(self.backup.is_dir())
        self.assertEqual(current["control"], "active")
        self.assertEqual(current["request"], request["request_id"])
        self.assertEqual(task["status"], "running")
        self.assertTrue(request_path.is_file())
        self.assertEqual(prepared["request_sha256"], digest(request_path))
        self.assertFalse(request["boundaries"]["vault_writes"])
        self.assertEqual(self.store.config()["worker"]["argv"], ["/usr/bin/false"])

    def test_recorded_bridge_fixtures_capture_real_start_and_completion_shapes(self):
        startup = read_json(FIXTURES / "orca-startup-bound.recorded.json")
        completed = read_json(FIXTURES / "orca-runtime-completed.recorded.json")
        self.assertEqual(startup["record"]["schema"], "orca-global-dispatch/v2")
        self.assertEqual(startup["interactive"]["schema"], "orca-interactive/v1")
        self.assertEqual(
            startup["interactive"]["submission_method"], "provider_startup_prompt"
        )
        self.assertEqual(startup["interactive"]["status"], "CLI_STARTED_PROMPT_BOUND")
        self.assertEqual(completed["interactive"]["status"], "CLI_EXITED")
        self.assertEqual(completed["interactive"]["returncode"], 0)
        self.assertEqual(completed["record"]["official_chain_status"], "complete")
        self.assertEqual(
            completed["capture"]["report_sha256"],
            completed["interactive"]["report_sha256"],
        )
        self.assertNotEqual(completed["record"]["state"], "DONE")
        self.assertNotIn("receipt", completed)

    def test_bind_completion_appends_parent_evidence_then_imports_and_pauses(self):
        _, request, request_path = self.prepare_request()
        outputs = self.make_worker_outputs(request, request_path)
        record_path = self.make_runtime(request, request_path)
        worker_run = read_json(outputs["run"])
        self.assertNotIn("parent_completion", worker_run)

        bound = bind_completion(
            self.state, request_path, record_path, self.artifacts / "todo-manual-result.json"
        )
        completed_run = read_json(outputs["run"])
        envelope = read_json(bound["result_path"])
        self.assertEqual(completed_run["parent_completion"]["appended_by"], "Main")
        self.assertTrue(completed_run["parent_completion"]["appended_after_worker_exit"])
        self.assertTrue(completed_run["parent_completion"]["worker_authored_sha256"])
        self.assertEqual(
            completed_run["parent_completion"]["orca"]["record"]["sha256"],
            bound["record_sha256"],
        )
        self.assertEqual(set(envelope["orca"]), {"job", "record"})
        self.assertNotIn("DELIVERED", json.dumps(completed_run))
        self.assertNotIn("receipt", envelope["orca"])

        imported = import_result(self.state, request_path, bound["result_path"])
        current = self.store.track("manual-trial")
        task = self.task_row(request["task_id"])
        stored = next(
            row for row in self.store.snapshot()["results"] if row["id"] == imported["result_id"]
        )
        self.assertEqual(current["control"], "paused")
        self.assertEqual(task["status"], "done")
        self.assertIn(bound["record_sha256"], stored["body"])
        self.assertEqual(
            set(imported["outputs"]),
            {"fresh-wiki.md", "fresh-structure-decision.md", "fresh-claims.json", "fresh-run.json"},
        )
        self.assertEqual(self.store.config()["worker"]["argv"], ["/usr/bin/false"])

    def test_startup_record_is_not_completion(self):
        _, request, request_path = self.prepare_request()
        self.make_worker_outputs(request, request_path)
        record_path = self.make_runtime(request, request_path, startup_only=True)
        with self.assertRaisesRegex(ValueError, "successful completed runtime"):
            bind_completion(
                self.state, request_path, record_path, self.artifacts / "todo-manual-result.json"
            )
        self.assertNotIn("parent_completion", read_json(self.artifacts / "fresh-run.json"))
        self.assertEqual(self.task_row(request["task_id"])["status"], "running")

    def test_startup_prompt_must_bind_current_request_and_frozen_hashes(self):
        _, request, request_path = self.prepare_request()
        self.make_worker_outputs(request, request_path)
        record_path = self.make_runtime(request, request_path, omit_skill_binding=True)
        with self.assertRaisesRegex(ValueError, "does not bind the claimed TODO request"):
            bind_completion(
                self.state, request_path, record_path, self.artifacts / "todo-manual-result.json"
            )
        self.assertEqual(self.task_row(request["task_id"])["status"], "running")

    def test_completion_report_hash_must_match_actual_report(self):
        _, request, request_path = self.prepare_request()
        self.make_worker_outputs(request, request_path)
        record_path = self.make_runtime(request, request_path)
        record = read_json(record_path)
        interactive_path = Path(record["interactive_status_path"])
        interactive = read_json(interactive_path)
        interactive["report_sha256"] = "0" * 64
        write_json(interactive_path, interactive)
        with self.assertRaisesRegex(ValueError, "report hash differs"):
            bind_completion(
                self.state, request_path, record_path, self.artifacts / "todo-manual-result.json"
            )

    def test_nonzero_orca_exit_cannot_bind_completion(self):
        _, request, request_path = self.prepare_request()
        self.make_worker_outputs(request, request_path)
        record_path = self.make_runtime(request, request_path)
        record = read_json(record_path)
        interactive_path = Path(record["interactive_status_path"])
        interactive = read_json(interactive_path)
        interactive["returncode"] = 19
        write_json(interactive_path, interactive)
        with self.assertRaisesRegex(ValueError, "successful completed runtime"):
            bind_completion(
                self.state, request_path, record_path, self.artifacts / "todo-manual-result.json"
            )

    def test_read_only_import_rejects_worker_side_effects(self):
        _, request, request_path = self.prepare_request()
        outputs = self.make_worker_outputs(request, request_path)
        run = read_json(outputs["run"])
        run["worker_authored"]["todo_result"]["changes"] = [
            {"path": "1.wiki/page.md", "content": "must not land"}
        ]
        write_json(outputs["run"], run)
        record_path = self.make_runtime(request, request_path)
        with self.assertRaisesRegex(ValueError, "cannot request Git"):
            bind_completion(
                self.state, request_path, record_path, self.artifacts / "todo-manual-result.json"
            )

    def test_worker_cannot_claim_different_frozen_skill_or_effects(self):
        _, request, request_path = self.prepare_request()
        self.make_worker_outputs(request, request_path, bind_skill=False)
        record_path = self.make_runtime(request, request_path)
        with self.assertRaisesRegex(ValueError, "skill manifest binding mismatch"):
            bind_completion(
                self.state, request_path, record_path, self.artifacts / "todo-manual-result.json"
            )
        self.assertEqual(self.task_row(request["task_id"])["status"], "running")

    def test_frozen_skill_source_change_blocks_bind(self):
        _, request, request_path = self.prepare_request()
        self.make_worker_outputs(request, request_path)
        record_path = self.make_runtime(request, request_path)
        self.skill.write_text("changed after freeze\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Skill source hash changed"):
            bind_completion(
                self.state, request_path, record_path, self.artifacts / "todo-manual-result.json"
            )
        self.assertEqual(self.task_row(request["task_id"])["status"], "running")

    def test_unfrozen_skill_manifest_cannot_start_a_task(self):
        self.skill_manifest = write_json(
            self.skill_manifest,
            {
                "schema": "knowledge-skill-source-freeze/v1",
                "frozen": False,
                "files": [{"path": str(self.skill), "sha256": digest(self.skill)}],
            },
        )
        with self.assertRaisesRegex(ValueError, "frozen=true"):
            self.prepare_request()
        self.assertEqual(self.store.track("manual-trial")["control"], "paused")
        self.assertFalse(self.backup.exists())

    def test_record_change_after_bind_fails_closed_on_import(self):
        _, request, request_path = self.prepare_request()
        self.make_worker_outputs(request, request_path)
        record_path = self.make_runtime(request, request_path)
        bound = bind_completion(
            self.state, request_path, record_path, self.artifacts / "todo-manual-result.json"
        )
        record = read_json(record_path)
        record["unreviewed_change"] = True
        write_json(record_path, record)
        with self.assertRaisesRegex(ValueError, "record hash mismatch"):
            import_result(self.state, request_path, bound["result_path"])
        self.assertEqual(self.task_row(request["task_id"])["status"], "running")

    def test_duplicate_completion_binding_is_idempotent_for_same_record(self):
        _, request, request_path = self.prepare_request()
        self.make_worker_outputs(request, request_path)
        record_path = self.make_runtime(request, request_path)
        result_path = self.artifacts / "todo-manual-result.json"
        first = bind_completion(self.state, request_path, record_path, result_path)
        second = bind_completion(self.state, request_path, record_path, result_path)
        self.assertEqual(first, second)
        self.assertEqual(digest(self.artifacts / "fresh-run.json"), first["outputs"]["fresh-run.json"])

    def test_manual_result_cannot_escape_registered_staging_path(self):
        _, request, request_path = self.prepare_request()
        self.make_worker_outputs(request, request_path)
        record_path = self.make_runtime(request, request_path)
        with self.assertRaisesRegex(ValueError, "registered staging path"):
            bind_completion(self.state, request_path, record_path, self.artifacts / "elsewhere.json")


if __name__ == "__main__":
    unittest.main()
