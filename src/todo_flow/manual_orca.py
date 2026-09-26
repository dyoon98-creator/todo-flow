"""Local, manually supervised Orca handoff for file-backed TODO Flow projects.

This module is a project-local extension, not an upstream ``todo-flow`` command.
It claims a TODO task before Main dispatches an Orca worker, then imports only a
request-bound, read-only result and verified stage outputs. It never starts Engine.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from .cli import runtime_guard
from .store import Conflict, Store, encode, fingerprint
from .worker import validate

REQUEST_SCHEMA = "todo-flow.manual-orca-request/v1"
RESULT_SCHEMA = "todo-flow.manual-orca-result/v1"
RUN_SCHEMA = "knowledge-flow-fresh-run/v1"
DISPATCH_SCHEMA = "orca-global-dispatch/v2"
BRIDGE_SCHEMA = "orca-provider-bridge/v1"
INTERACTIVE_SCHEMA = "orca-interactive/v1"
REQUIRED_OUTPUTS = (
    "fresh-wiki.md",
    "fresh-structure-decision.md",
    "fresh-claims.json",
    "fresh-run.json",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value):
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(canonical.encode("utf-8"))


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _inside(path, root):
    try:
        Path(path).resolve(strict=False).relative_to(Path(root).resolve(strict=False))
        return True
    except ValueError:
        return False


def _absolute_file(value, label):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be an existing absolute regular file: {value}")
    return path.resolve(strict=True)


def _verify_sources(manifest_path):
    manifest_path = _absolute_file(manifest_path, "Source manifest")
    manifest = read_json(manifest_path)
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("Source manifest must be a non-empty array")
    source_root = (manifest_path.parent / "fresh-input").resolve(strict=True)
    verified = []
    seen = set()
    for row in manifest:
        if not isinstance(row, dict) or not isinstance(row.get("snapshot"), str):
            raise ValueError("Source manifest entry requires snapshot and sha256")
        path = _absolute_file(row["snapshot"], "Source snapshot")
        if not _inside(path, source_root):
            raise ValueError("Source snapshot must remain inside fresh-input")
        digest = row.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError("Source snapshot requires a lowercase SHA-256")
        if sha256_file(path) != digest:
            raise ValueError(f"Source snapshot hash changed: {path}")
        if str(path) in seen:
            raise ValueError(f"Duplicate source snapshot: {path}")
        seen.add(str(path))
        verified.append({"path": str(path), "sha256": digest})
    return manifest_path, sha256_file(manifest_path), verified


def _verify_skills(manifest_path):
    manifest_path = _absolute_file(manifest_path, "Skill freeze manifest")
    manifest = read_json(manifest_path)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "knowledge-skill-source-freeze/v1"
        or manifest.get("frozen") is not True
        or not isinstance(manifest.get("files"), list)
        or not manifest["files"]
    ):
        raise ValueError(
            "Skill manifest must use knowledge-skill-source-freeze/v1 with frozen=true"
        )
    verified = []
    seen = set()
    for row in manifest["files"]:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("Skill manifest entry requires path and sha256")
        path = _absolute_file(row["path"], "Skill source")
        digest = row.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError("Skill source requires a lowercase SHA-256")
        if sha256_file(path) != digest:
            raise ValueError(f"Skill source hash changed: {path}")
        if str(path) in seen:
            raise ValueError(f"Duplicate skill source: {path}")
        seen.add(str(path))
        verified.append({"path": str(path), "sha256": digest})
    return manifest_path, sha256_file(manifest_path), verified


def _document(track):
    value = track["document"]
    return json.loads(value) if isinstance(value, str) else value


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise Conflict(f"Refusing to replace existing manual handoff file: {path}")
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        os.unlink(temporary)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_replace_json(path, value):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Refusing to replace non-regular JSON output: {path}")
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _backup_state(state, backup, project_root):
    state = Path(state).resolve(strict=True)
    backup = Path(backup).expanduser().absolute()
    if backup.exists() or backup.is_symlink():
        raise Conflict(f"Backup destination already exists: {backup}")
    if _inside(backup, state) or _inside(backup, project_root):
        raise ValueError("State backup must be outside both TODO state and vault")
    if not backup.parent.is_dir() or backup.parent.is_symlink():
        raise ValueError("State backup parent must be an existing regular directory")
    staging = Path(tempfile.mkdtemp(prefix=".todo-flow-backup-", dir=backup.parent))
    try:
        copy = staging / "state"
        shutil.copytree(state, copy, symlinks=True)
        os.replace(copy, backup)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return str(backup)


def prepare(state, track_id, purpose, contract, source_manifest, skill_manifest, lease_seconds, backup):
    state = Path(state).resolve(strict=True)
    contract = _absolute_file(contract, "Fresh-trial contract")
    source_manifest, source_hash, sources = _verify_sources(source_manifest)
    skill_manifest, skill_hash, skills = _verify_skills(skill_manifest)
    contract_hash = sha256_file(contract)

    with runtime_guard(state):
        store = Store(state)
        config = store.config()
        project_root = Path(config["repo"]).resolve(strict=True)
        artifact_root = contract.parent.resolve(strict=True)
        if _inside(artifact_root, project_root):
            raise ValueError("Fresh-trial outputs must be staged outside the vault")
        backup_path = _backup_state(state, backup, project_root)
        track = store.track(track_id)
        document = _document(track)
        binding = "manual-orca:" + fingerprint(
            [track_id, purpose, contract_hash, source_hash, skill_hash]
        )
        task = store.manual_claim(
            track_id,
            purpose,
            owner="manual-orca-extension",
            ttl=lease_seconds,
            binding=binding,
        )
        request_path = state / "attempts" / task["attempt"] / "manual-request.json"
        request = {
            "schema": REQUEST_SCHEMA,
            "created_at": time.time(),
            "state_root": str(state),
            "state_backup": backup_path,
            "project_root": str(project_root),
            "artifact_root": str(artifact_root),
            "request_id": task["request_id"],
            "track_id": track_id,
            "task_id": task["id"],
            "attempt_id": task["attempt"],
            "generation": task["generation"],
            "owner": task["owner"],
            "document_revision": task["input_revision"],
            "purpose": task["purpose"],
            "track_document": {
                "title": document.get("title"),
                "goal": document.get("goal"),
                "scope": document.get("scope"),
                "evidence": document.get("evidence"),
                "conditions": document.get("conditions", []),
            },
            "contract": {"path": str(contract), "sha256": contract_hash},
            "source_manifest": {
                "path": str(source_manifest),
                "sha256": source_hash,
                "files": sources,
            },
            "skill_manifest": {
                "path": str(skill_manifest),
                "sha256": skill_hash,
                "files": skills,
            },
            "required_outputs": [str(artifact_root / name) for name in REQUIRED_OUTPUTS],
            "boundaries": {
                "worker_path": "Main Orca policy dispatch and exact run-record retrieval",
                "read_only": True,
                "vault_writes": False,
                "git_effects": False,
                "forbidden_source": ["published wiki", "draft backups", "prior numerical report"],
            },
        }
        try:
            _atomic_json(request_path, request)
        except Exception:
            store.control(track_id, "cancel")
            raise
        return {
            "request": request,
            "request_path": str(request_path),
            "request_sha256": sha256_file(request_path),
            "state_backup": backup_path,
        }


def _required_object(value, field, label):
    row = value.get(field)
    if not isinstance(row, dict):
        raise ValueError(f"{label} requires object field {field}")
    return row


def _check_external_record(record, label, project_root):
    if not isinstance(record, dict):
        raise ValueError(f"{label} record requires path and sha256")
    path = _absolute_file(record.get("path", ""), f"{label} record")
    if _inside(path, project_root):
        raise ValueError(f"{label} record must remain outside the vault")
    digest = record.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest) or sha256_file(path) != digest:
        raise ValueError(f"{label} record hash mismatch")
    try:
        body = read_json(path)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} record must be JSON") from error
    return path, body


def _verify_orca_startup(request, request_hash, orca, project_root):
    if set(orca) - {"job", "record"}:
        raise ValueError("Manual Orca binding accepts only the exact bridge job and record")
    job = orca.get("job")
    if not isinstance(job, str) or not job:
        raise ValueError("Manual Orca binding requires bridge_job")
    record_path, record = _check_external_record(orca.get("record", {}), "Orca run", project_root)
    if (
        record.get("schema") != DISPATCH_SCHEMA
        or record.get("bridge_schema") != BRIDGE_SCHEMA
        or record.get("bridge_job") != job
        or record.get("job") != job
        or record.get("name") != job
    ):
        raise ValueError("Orca record is not the exact global-dispatch provider bridge job")

    state_dir_value = record.get("state_dir")
    state_dir_raw = Path(state_dir_value) if isinstance(state_dir_value, str) else Path()
    if not state_dir_raw.is_absolute() or state_dir_raw.is_symlink() or not state_dir_raw.is_dir():
        raise ValueError("Orca bridge record requires its existing regular state_dir")
    state_dir = state_dir_raw.resolve(strict=True)
    if _inside(state_dir, project_root):
        raise ValueError("Orca runtime state must remain outside the vault")
    state_root_value = record.get("state_root")
    state_root_raw = Path(state_root_value) if isinstance(state_root_value, str) else Path()
    if not state_root_raw.is_absolute() or state_root_raw.is_symlink() or not state_root_raw.is_dir():
        raise ValueError("Orca bridge state_root must be an existing regular directory")
    if not _inside(state_dir, state_root_raw.resolve(strict=True)):
        raise ValueError("Orca state_dir is outside its recorded state_root")

    source_instruction = _absolute_file(record.get("instruction", ""), "Orca dispatch instruction")
    if _inside(source_instruction, project_root):
        raise ValueError("Orca dispatch instruction must remain outside the vault")
    source_instruction_hash = record.get("instruction_sha256")
    if (
        not isinstance(source_instruction_hash, str)
        or not SHA256.fullmatch(source_instruction_hash)
        or sha256_file(source_instruction) != source_instruction_hash
    ):
        raise ValueError("Orca dispatch instruction hash mismatch")

    startup_prompt = _absolute_file(str(state_dir / "instruction.md"), "Orca startup prompt")
    prompt_hash = record.get("prompt_sha256")
    if not isinstance(prompt_hash, str) or not SHA256.fullmatch(prompt_hash) or sha256_file(startup_prompt) != prompt_hash:
        raise ValueError("Orca startup prompt is not bound by the global-dispatch record")
    prompt_text = startup_prompt.read_text(encoding="utf-8")
    request_bindings = {
        "request_id": request["request_id"],
        "task_id": request["task_id"],
        "attempt_id": request["attempt_id"],
        "request_sha256": request_hash,
        "contract_sha256": request["contract"]["sha256"],
        "source_manifest_sha256": request["source_manifest"]["sha256"],
        "skill_manifest_sha256": request["skill_manifest"]["sha256"],
    }
    if any(value not in prompt_text for value in request_bindings.values()):
        raise ValueError("Orca startup prompt does not bind the claimed TODO request and frozen sources")

    interactive_path = _absolute_file(
        record.get("interactive_status_path", ""), "Orca interactive status"
    )
    if not _inside(interactive_path, state_dir):
        raise ValueError("Orca interactive status must be inside its recorded state_dir")
    interactive = read_json(interactive_path)
    if (
        interactive.get("schema") != INTERACTIVE_SCHEMA
        or interactive.get("submission_method") != "provider_startup_prompt"
        or not isinstance(interactive.get("provider"), str)
        or not interactive.get("provider")
        or not isinstance(interactive.get("prompt_sha256"), str)
        or not SHA256.fullmatch(interactive["prompt_sha256"])
    ):
        raise ValueError("Orca interactive status is not a provider startup-prompt record")
    if (
        interactive.get("status") != "CLI_EXITED"
        or type(interactive.get("returncode")) is not int
        or interactive["returncode"] != 0
        or type(interactive.get("provider_returncode")) is not int
        or interactive["provider_returncode"] != 0
    ):
        raise ValueError("Orca interactive status does not prove a successful completed runtime")
    if (
        record.get("provider_complete") is not True
        or record.get("official_dispatch_status") != "complete"
        or record.get("official_session_status") != "complete"
        or record.get("official_chain_status") != "complete"
    ):
        raise ValueError("Orca global-dispatch record does not prove completed official runtime")

    report_path = _absolute_file(record.get("report_path", ""), "Orca completion report")
    if _inside(report_path, project_root):
        raise ValueError("Orca completion report must remain outside the vault")
    report_hash = interactive.get("report_sha256")
    if not isinstance(report_hash, str) or not SHA256.fullmatch(report_hash) or sha256_file(report_path) != report_hash:
        raise ValueError("Orca completion report hash differs from interactive runtime evidence")

    return {
        "job": job,
        "record": {"path": str(record_path), "sha256": sha256_file(record_path)},
        "instruction": {"path": str(source_instruction), "sha256": source_instruction_hash},
        "startup_prompt": {"path": str(startup_prompt), "sha256": prompt_hash},
        "interactive": {
            "path": str(interactive_path),
            "sha256": sha256_file(interactive_path),
            "schema": interactive["schema"],
            "provider": interactive["provider"],
            "status": interactive["status"],
            "submission_method": interactive["submission_method"],
            "returncode": interactive["returncode"],
            "provider_returncode": interactive["provider_returncode"],
            "prompt_sha256": interactive["prompt_sha256"],
        },
        "report": {"path": str(report_path), "sha256": report_hash},
        "request_binding": request_bindings,
    }


def _verify_worker_facts(request, request_hash, worker):
    if not isinstance(worker, dict):
        raise ValueError("fresh-run.json requires worker_authored facts")
    expected_todo = {
        "request_id": request["request_id"],
        "task_id": request["task_id"],
        "attempt_id": request["attempt_id"],
        "request_sha256": request_hash,
    }
    todo = _required_object(worker, "todo", "fresh-run worker_authored")
    if any(todo.get(key) != value for key, value in expected_todo.items()):
        raise ValueError("fresh-run worker-authored TODO request binding mismatch")
    if worker.get("source_manifest_sha256") != request["source_manifest"]["sha256"]:
        raise ValueError("fresh-run worker-authored source manifest binding mismatch")
    if worker.get("skill_manifest_sha256") != request["skill_manifest"]["sha256"]:
        raise ValueError("fresh-run worker-authored skill manifest binding mismatch")

    artifact_root = Path(request["artifact_root"]).resolve(strict=True)
    project_root = Path(request["project_root"]).resolve(strict=True)
    output_rows = worker.get("outputs")
    required_names = set(REQUIRED_OUTPUTS) - {"fresh-run.json"}
    if not isinstance(output_rows, list):
        raise ValueError("fresh-run worker_authored outputs must be an array")
    by_name = {}
    for row in output_rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError("Each worker-authored output requires name and sha256")
        name, digest = row["name"], row.get("sha256")
        if name in by_name or name not in required_names or not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError("Worker-authored outputs contain duplicate, unknown, or invalid entries")
        path = _absolute_file(str(artifact_root / name), "Worker stage output")
        if _inside(path, project_root) or sha256_file(path) != digest:
            raise ValueError(f"Worker-authored output hash mismatch: {name}")
        by_name[name] = {"path": str(path), "sha256": digest}
    if set(by_name) != required_names:
        raise ValueError("fresh-run worker_authored must bind all three stage outputs")

    wiki = Path(by_name["fresh-wiki.md"]["path"]).read_text(encoding="utf-8").strip()
    decision = Path(by_name["fresh-structure-decision.md"]["path"]).read_text(encoding="utf-8").strip()
    if not wiki or not decision:
        raise ValueError("Fresh wiki and structure decision must be non-empty")
    claims = read_json(by_name["fresh-claims.json"]["path"])
    if not isinstance(claims, list) or not claims:
        raise ValueError("Claims report must be a non-empty JSON array")
    source_hashes = {row["path"]: row["sha256"] for row in request["source_manifest"]["files"]}
    for row in claims:
        required = ("output_passage", "source_path", "source_excerpt", "source_sha256", "source_line", "interpretation")
        if not isinstance(row, dict) or any(not row.get(key) for key in required):
            raise ValueError("Each claim requires output passage, source excerpt/line/hash, and interpretation")
        if (
            type(row["source_line"]) is not int
            or row["source_line"] < 1
            or source_hashes.get(row["source_path"]) != row["source_sha256"]
        ):
            raise ValueError("Claim source path, line, or hash differs from frozen source manifest")

    checks = _required_object(worker, "checks", "fresh-run worker_authored")
    helper = _required_object(checks, "path_metadata_link_helper", "fresh-run checks")
    if type(helper.get("exit_code")) is not int or helper["exit_code"] != 0 or not any(
        "validate_vault_page.py" in str(arg) for arg in helper.get("argv", [])
    ):
        raise ValueError("fresh-run must record a passing validate_vault_page.py command")
    repeat = _required_object(checks, "repeat_assessment", "fresh-run checks")
    wiki_hash = by_name["fresh-wiki.md"]["sha256"]
    if (
        repeat.get("wiki_sha256_before") != wiki_hash
        or repeat.get("wiki_sha256_after") != wiki_hash
        or repeat.get("updated_before") != repeat.get("updated_after")
    ):
        raise ValueError("Repeat assessment did not preserve stage bytes and updated metadata")

    result = _required_object(worker, "todo_result", "fresh-run worker_authored")
    validate(result, "work")
    if result.get("changes") or result.get("publish") or result.get("verify") or result.get("next"):
        raise ValueError("Manual read-only result cannot request Git, verification, or follow-up effects")
    return by_name, result


def _parent_completion(orca_evidence, worker_authored):
    return {
        "appended_by": "Main",
        "appended_after_worker_exit": True,
        "worker_authored_sha256": _canonical_sha256(worker_authored),
        "orca": orca_evidence,
    }


def _verify_fresh_outputs(request, request_hash, envelope, orca_evidence):
    artifact_root = Path(request["artifact_root"]).resolve(strict=True)
    project_root = Path(request["project_root"]).resolve(strict=True)
    rows = envelope.get("outputs")
    if not isinstance(rows, list):
        raise ValueError("Manual result outputs must be an array")
    by_name = {}
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("name", "path", "sha256")):
            raise ValueError("Each output requires name, path, and sha256")
        if row["name"] in by_name:
            raise ValueError("Duplicate output name")
        path = _absolute_file(row["path"], "Stage output")
        expected = (artifact_root / row["name"]).resolve(strict=True)
        if path != expected or _inside(path, project_root):
            raise ValueError(f"Output must use its declared staging path outside the vault: {row['name']}")
        if not SHA256.fullmatch(row["sha256"]) or sha256_file(path) != row["sha256"]:
            raise ValueError(f"Stage output hash mismatch: {row['name']}")
        by_name[row["name"]] = {"path": str(path), "sha256": row["sha256"]}
    if set(by_name) != set(REQUIRED_OUTPUTS):
        raise ValueError("Manual result must import all four fresh-trial outputs")

    run = read_json(by_name["fresh-run.json"]["path"])
    if run.get("schema") != RUN_SCHEMA:
        raise ValueError(f"fresh-run.json must use {RUN_SCHEMA}")
    worker = _required_object(run, "worker_authored", "fresh-run.json")
    worker_outputs, worker_result = _verify_worker_facts(request, request_hash, worker)
    if worker_outputs != {name: by_name[name] for name in worker_outputs}:
        raise ValueError("fresh-run worker-authored output hashes differ from staged outputs")
    if envelope.get("todo_result") != worker_result:
        raise ValueError("Manual result TODO output differs from worker-authored result")
    if run.get("parent_completion") != _parent_completion(orca_evidence, worker):
        raise ValueError("fresh-run parent completion provenance differs from actual Orca evidence")
    run_outputs = worker.get("outputs")
    expected_run_outputs = [
        {"name": name, "sha256": worker_outputs[name]["sha256"]}
        for name in ("fresh-wiki.md", "fresh-structure-decision.md", "fresh-claims.json")
    ]
    if run_outputs != expected_run_outputs:
        raise ValueError("fresh-run worker-authored output hashes differ from staged outputs")
    return by_name


def _load_request(state, request_path):
    state = Path(state).resolve(strict=True)
    request_path = _absolute_file(request_path, "Manual request")
    request = read_json(request_path)
    if request.get("schema") != REQUEST_SCHEMA or request.get("state_root") != str(state):
        raise ValueError("Manual request schema/state mismatch")
    expected_request_path = state / "attempts" / request["attempt_id"] / "manual-request.json"
    if request_path != expected_request_path.resolve(strict=True):
        raise ValueError("Manual request is not the registered attempt request")
    request_hash = sha256_file(request_path)

    contract = _absolute_file(request["contract"]["path"], "Fresh-trial contract")
    if sha256_file(contract) != request["contract"]["sha256"]:
        raise ValueError("Fresh-trial contract changed after task claim")
    source_path, source_hash, source_rows = _verify_sources(request["source_manifest"]["path"])
    skill_path, skill_hash, skill_rows = _verify_skills(request["skill_manifest"]["path"])
    if (
        str(source_path) != request["source_manifest"]["path"]
        or source_hash != request["source_manifest"]["sha256"]
        or source_rows != request["source_manifest"]["files"]
        or str(skill_path) != request["skill_manifest"]["path"]
        or skill_hash != request["skill_manifest"]["sha256"]
        or skill_rows != request["skill_manifest"]["files"]
    ):
        raise ValueError("Frozen source or skill hashes changed after task claim")
    return state, request, request_hash, Path(request["project_root"]).resolve(strict=True)


def bind_completion(state, request_path, record_path, result_path):
    """Append Main-owned completion provenance after the exact Orca worker exits."""
    _, request, request_hash, project_root = _load_request(state, request_path)
    artifact_root = Path(request["artifact_root"]).resolve(strict=True)
    fresh_run_path = _absolute_file(str(artifact_root / "fresh-run.json"), "Worker fresh-run output")
    result_path = Path(result_path).absolute()
    expected_result_path = artifact_root / "todo-manual-result.json"
    if result_path.resolve(strict=False) != expected_result_path.resolve(strict=False):
        raise ValueError("Manual result must be written to the registered staging path")
    if _inside(result_path, project_root):
        raise ValueError("Manual result must remain outside the vault")

    record_path = _absolute_file(record_path, "Orca global-dispatch record")
    if _inside(record_path, project_root):
        raise ValueError("Orca global-dispatch record must remain outside the vault")
    record = read_json(record_path)
    job = record.get("bridge_job")
    orca_input = {
        "job": job,
        "record": {"path": str(record_path), "sha256": sha256_file(record_path)},
    }
    orca_evidence = _verify_orca_startup(request, request_hash, orca_input, project_root)

    run = read_json(fresh_run_path)
    if run.get("schema") != RUN_SCHEMA:
        raise ValueError(f"fresh-run.json must use {RUN_SCHEMA}")
    worker = _required_object(run, "worker_authored", "fresh-run.json")
    worker_outputs, worker_result = _verify_worker_facts(request, request_hash, worker)
    parent_completion = _parent_completion(orca_evidence, worker)
    if "parent_completion" in run and run["parent_completion"] != parent_completion:
        raise Conflict("fresh-run.json already has different parent completion provenance")
    completed_run = {**run, "parent_completion": parent_completion}
    run_bytes = (json.dumps(completed_run, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    outputs = [
        {"name": name, "path": str(artifact_root / name), "sha256": sha256_file(artifact_root / name)}
        for name in ("fresh-wiki.md", "fresh-structure-decision.md", "fresh-claims.json")
    ]
    outputs.append({"name": "fresh-run.json", "path": str(fresh_run_path), "sha256": sha256_bytes(run_bytes)})
    binding = {
        "request_id": request["request_id"],
        "task_id": request["task_id"],
        "attempt_id": request["attempt_id"],
        "request_sha256": request_hash,
        "contract_sha256": request["contract"]["sha256"],
        "source_manifest_sha256": request["source_manifest"]["sha256"],
        "skill_manifest_sha256": request["skill_manifest"]["sha256"],
    }
    envelope = {
        "schema": RESULT_SCHEMA,
        "request": binding,
        "orca": {"job": orca_evidence["job"], "record": orca_evidence["record"]},
        "outputs": outputs,
        "todo_result": worker_result,
    }

    if result_path.exists() or result_path.is_symlink():
        if result_path.is_symlink() or not result_path.is_file() or read_json(result_path) != envelope:
            raise Conflict(f"Refusing to replace existing manual result: {result_path}")
    else:
        if not result_path.parent.is_dir() or result_path.parent.is_symlink():
            raise ValueError("Manual result parent must be an existing regular directory")
    if "parent_completion" not in run or fresh_run_path.read_bytes() != run_bytes:
        _atomic_replace_json(fresh_run_path, completed_run)
    if not result_path.exists():
        _atomic_json(result_path, envelope)
    return {
        "request_id": request["request_id"],
        "job": orca_evidence["job"],
        "record_sha256": orca_evidence["record"]["sha256"],
        "result_path": str(result_path),
        "result_sha256": sha256_file(result_path),
        "outputs": {row["name"]: row["sha256"] for row in outputs},
    }


def import_result(state, request_path, result_path):
    state, request, request_hash, project_root = _load_request(state, request_path)
    result_path = _absolute_file(result_path, "Manual result")
    if _inside(result_path, project_root):
        raise ValueError("Manual result must remain outside the vault")

    envelope = read_json(result_path)
    if envelope.get("schema") != RESULT_SCHEMA:
        raise ValueError(f"Manual result must use {RESULT_SCHEMA}")
    binding = _required_object(envelope, "request", "Manual result")
    expected_binding = {
        "request_id": request["request_id"],
        "task_id": request["task_id"],
        "attempt_id": request["attempt_id"],
        "request_sha256": request_hash,
        "contract_sha256": request["contract"]["sha256"],
        "source_manifest_sha256": request["source_manifest"]["sha256"],
        "skill_manifest_sha256": request["skill_manifest"]["sha256"],
    }
    if any(binding.get(key) != value for key, value in expected_binding.items()):
        raise ValueError("Manual result request/source/skill binding mismatch")

    orca = _required_object(envelope, "orca", "Manual result")
    orca_evidence = _verify_orca_startup(request, request_hash, orca, project_root)
    outputs = _verify_fresh_outputs(request, request_hash, envelope, orca_evidence)

    result = envelope.get("todo_result")
    if not isinstance(result, dict):
        raise ValueError("Manual result requires TODO worker result object")
    output_hashes = ", ".join(f"{name}={row['sha256']}" for name, row in outputs.items())
    provenance = (
        f"\n\nManual Orca import: request={request['request_id']}; task={request['task_id']}; "
        f"attempt={request['attempt_id']}; job={orca_evidence['job']}; "
        f"record_sha256={orca_evidence['record']['sha256']}; "
        f"report_sha256={orca_evidence['report']['sha256']}; "
        f"source_manifest_sha256={request['source_manifest']['sha256']}; "
        f"skill_manifest_sha256={request['skill_manifest']['sha256']}; outputs[{output_hashes}]"
    )
    result = {**result, "summary": result["summary"] + provenance}
    task = {
        "id": request["task_id"],
        "track": request["track_id"],
        "kind": "work",
        "owner": request["owner"],
        "generation": request["generation"],
        "input_revision": request["document_revision"],
        "attempt": request["attempt_id"],
    }
    with runtime_guard(state):
        store = Store(state)
        with store.transaction() as c:
            result_id = store.finish(task, result, connection=c)
            c.execute(
                "UPDATE tracks SET control='paused',updated=? WHERE id=? AND control='active'",
                (time.time(), request["track_id"]),
            )
            store.event(
                c,
                "execution.control",
                request["track_id"],
                {"action": "pause", "control": "paused", "reason": "manual result imported"},
            )
    return {
        "result_id": result_id,
        "request_id": request["request_id"],
        "task_id": request["task_id"],
        "attempt_id": request["attempt_id"],
        "orca_job": orca_evidence["job"],
        "source_manifest_sha256": request["source_manifest"]["sha256"],
        "skill_manifest_sha256": request["skill_manifest"]["sha256"],
        "outputs": {name: row["sha256"] for name, row in outputs.items()},
    }


def parser():
    root = argparse.ArgumentParser(
        prog="python -m todo_flow.manual_orca",
        description="Local extension; not an upstream todo-flow command.",
    )
    commands = root.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="start and claim a manual Orca task")
    prepare_parser.add_argument("--state", required=True)
    prepare_parser.add_argument("--track", required=True)
    prepare_parser.add_argument("--purpose", required=True)
    prepare_parser.add_argument("--contract", required=True)
    prepare_parser.add_argument("--source-manifest", required=True)
    prepare_parser.add_argument("--skill-manifest", required=True)
    prepare_parser.add_argument("--backup", required=True)
    prepare_parser.add_argument("--lease-seconds", type=int, default=21600)
    bind_parser = commands.add_parser(
        "bind-completion", help="append Main-owned evidence after the actual Orca runtime exits"
    )
    bind_parser.add_argument("--state", required=True)
    bind_parser.add_argument("--request", required=True)
    bind_parser.add_argument("--record", required=True)
    bind_parser.add_argument("--result", required=True)
    import_parser = commands.add_parser("import-result", help="verify and import actual Orca outputs")
    import_parser.add_argument("--state", required=True)
    import_parser.add_argument("--request", required=True)
    import_parser.add_argument("--result", required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare":
            if args.lease_seconds < 60 or args.lease_seconds > 86400:
                raise ValueError("Lease must be between 60 and 86400 seconds")
            output = prepare(
                args.state,
                args.track,
                args.purpose,
                args.contract,
                args.source_manifest,
                args.skill_manifest,
                args.lease_seconds,
                args.backup,
            )
        elif args.command == "bind-completion":
            output = bind_completion(args.state, args.request, args.record, args.result)
        else:
            output = import_result(args.state, args.request, args.result)
        print(encode(output))
    except (ValueError, Conflict, RuntimeError, OSError) as error:
        print(encode({"error": str(error)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
