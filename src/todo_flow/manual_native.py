"""Small request-bound bridge for a supervised native TODO worker.

Unlike ``manual_orca``, this extension records no Orca transport evidence. Main
claims one current TODO task, runs the bounded native check, then imports its
hash-bound result through Store.finish(). It never starts Engine/trackrun.
"""

import hashlib
import json
import time
from pathlib import Path

from .cli import runtime_guard
from .manual_orca import _absolute_file, _atomic_json, _backup_state, _document, _inside, _verify_skills, _verify_sources, read_json, sha256_file
from .store import Conflict, Store, encode, fingerprint
from .worker import validate

REQUEST_SCHEMA = "todo-flow.manual-native-request/v1"
RESULT_SCHEMA = "todo-flow.manual-native-result/v1"


def prepare(state, track_id, purpose, contract_path, source_manifest_path,
            skill_manifest_path, output_names, backup, owner="manual-native-worker",
            lease_seconds=21600):
    """Back up TODO state, freeze inputs, and claim one task before work starts."""
    state = Path(state).resolve(strict=True)
    contract = _absolute_file(contract_path, "Native-run contract")
    source_manifest, source_hash, sources = _verify_sources(source_manifest_path)
    skill_manifest, skill_hash, skills = _verify_skills(skill_manifest_path)
    output_names = list(output_names)
    if (not output_names or len(output_names) != len(set(output_names))
            or any(not isinstance(x, str) or Path(x).name != x for x in output_names)):
        raise ValueError("Outputs must be unique file names")
    with runtime_guard(state):
        store = Store(state)
        project_root = Path(store.config()["repo"]).resolve(strict=True)
        artifact_root = contract.parent.resolve(strict=True)
        if _inside(artifact_root, project_root):
            raise ValueError("Native outputs must remain outside the vault")
        backup_path = _backup_state(state, backup, project_root)
        current = store.track(track_id)
        binding = "manual-native:" + fingerprint([
            track_id, purpose, sha256_file(contract), source_hash, skill_hash, output_names
        ])
        task = store.manual_claim(track_id, purpose, owner, lease_seconds, binding)
        path = state / "attempts" / task["attempt"] / "manual-native-request.json"
        request = {
            "schema": REQUEST_SCHEMA,
            "state_root": str(state),
            "state_backup": backup_path,
            "project_root": str(project_root),
            "artifact_root": str(artifact_root),
            "request_id": task["request_id"],
            "task_id": task["id"],
            "attempt_id": task["attempt"],
            "generation": task["generation"],
            "owner": owner,
            "track_id": track_id,
            "document_revision": current["revision"],
            "track_document": _document(current),
            "contract": {"path": str(contract), "sha256": sha256_file(contract)},
            "source_manifest": {"path": str(source_manifest), "sha256": source_hash, "files": sources},
            "skill_manifest": {"path": str(skill_manifest), "sha256": skill_hash, "files": skills},
            "outputs": output_names,
            "execution_mode": "native",
            "orca_evidence": None,
        }
        try:
            _atomic_json(path, request)
        except Exception:
            store.control(track_id, "cancel")
            raise
    return {"request": request, "request_path": str(path), "request_sha256": sha256_file(path)}


def import_result(state, request_path, result_path):
    """Verify current request, inputs, outputs and conditions; finish atomically."""
    state = Path(state).resolve(strict=True)
    request_path = _absolute_file(request_path, "Native TODO request")
    request = read_json(request_path)
    if request.get("schema") != REQUEST_SCHEMA or request.get("state_root") != str(state):
        raise ValueError("Native request schema/state mismatch")
    expected_path = state / "attempts" / request["attempt_id"] / "manual-native-request.json"
    if request_path != expected_path.resolve(strict=True):
        raise ValueError("Request is not registered to this TODO attempt")
    request_hash = sha256_file(request_path)
    contract = _absolute_file(request["contract"]["path"], "Native-run contract")
    source_path, source_hash, sources = _verify_sources(request["source_manifest"]["path"])
    skill_path, skill_hash, skills = _verify_skills(request["skill_manifest"]["path"])
    if (sha256_file(contract) != request["contract"]["sha256"]
            or str(source_path) != request["source_manifest"]["path"]
            or source_hash != request["source_manifest"]["sha256"]
            or sources != request["source_manifest"]["files"]
            or str(skill_path) != request["skill_manifest"]["path"]
            or skill_hash != request["skill_manifest"]["sha256"]
            or skills != request["skill_manifest"]["files"]):
        raise ValueError("Claimed contract/source/skill input changed")

    artifact_root = Path(request["artifact_root"]).resolve(strict=True)
    project_root = Path(request["project_root"]).resolve(strict=True)
    result_path = _absolute_file(result_path, "Native result")
    if result_path != (artifact_root / "manual-native-result.json").resolve(strict=True):
        raise ValueError("Result must use the claimed staging path")
    envelope = read_json(result_path)
    expected_binding = {"request_id": request["request_id"], "task_id": request["task_id"],
                        "attempt_id": request["attempt_id"], "request_sha256": request_hash}
    if envelope.get("schema") != RESULT_SCHEMA or envelope.get("todo") != expected_binding:
        raise ValueError("Result does not bind the current native TODO request/task/attempt")

    outputs = {}
    for row in envelope.get("outputs", []):
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("name", "path", "sha256")):
            raise ValueError("Output requires name, path, and sha256")
        name = row["name"]
        path = _absolute_file(row["path"], "Native output")
        if (name in outputs or name not in request["outputs"]
                or path != (artifact_root / name).resolve(strict=True)
                or _inside(path, project_root) or sha256_file(path) != row["sha256"]):
            raise ValueError("Native output name/path/hash mismatch: " + name)
        outputs[name] = {"path": str(path), "sha256": row["sha256"]}
    if set(outputs) != set(request["outputs"]):
        raise ValueError("Result must bind every requested output once")

    result = envelope.get("todo_result")
    validate(result, "work")
    if any(result.get(k) for k in ("changes", "publish", "verify", "next", "question")):
        raise ValueError("Native read-only import cannot request engine or Git effects")
    conditions = request["track_document"].get("conditions", [])
    expected_ids = {row["id"] for row in conditions}
    result_conditions = result.get("conditions", [])
    actual_ids = [row.get("id") for row in result_conditions if isinstance(row, dict)]
    if set(actual_ids) != expected_ids or len(actual_ids) != len(expected_ids):
        raise ValueError("Result must evaluate every current track condition exactly once")
    if any(not row.get("evidence", "").strip() for row in result_conditions):
        raise ValueError("Each condition requires concrete evidence")

    bound_result = {
        **result,
        "manual_execution": {
            "mode": "native", "request_id": request["request_id"],
            "task_id": request["task_id"], "attempt_id": request["attempt_id"],
            "request_sha256": request_hash, "result_sha256": sha256_file(result_path),
            "outputs": outputs, "source_manifest_sha256": source_hash,
            "skill_manifest_sha256": skill_hash,
        },
    }
    task = {"id": request["task_id"], "track": request["track_id"],
            "attempt": request["attempt_id"], "generation": request["generation"],
            "input_revision": request["document_revision"], "owner": request["owner"]}
    with runtime_guard(state):
        store = Store(state)
        with store.transaction() as connection:
            store.assert_claim(connection, task)
            result_id = store.finish(task, bound_result, connection=connection)
            connection.execute("UPDATE tracks SET control='paused',updated=? WHERE id=? AND control='active'",
                               (time.time(), request["track_id"]))
            store.event(connection, "execution.control", request["track_id"],
                        {"action": "pause", "control": "paused", "reason": "native result imported"})
    return {"result_id": result_id, "request_id": request["request_id"],
            "task_id": request["task_id"], "attempt_id": request["attempt_id"],
            "source_manifest_sha256": source_hash, "skill_manifest_sha256": skill_hash,
            "outputs": {name: row["sha256"] for name, row in outputs.items()}}
