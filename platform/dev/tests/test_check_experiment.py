"""check_experiment.py (experiments spec part 05, *check_experiment.py [<name>]*, decisions 17/18/23).

Most tests reuse the real repo's threats/paths/mitigations/fixtures/tests (as test_validate.py does)
and override only `experiments_dir` with a tmp-dir fixture experiment, per the plan: the fixture
experiments used here are never added to experiments/ itself (the spe-experiments template offers
every file there as a preset).
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
CHECK_EXPERIMENT = REPO / "check_experiment.py"

sys.path.insert(0, str(REPO))
import check_experiment as ce  # noqa: E402


def real_dirs(**overrides) -> dict:
    d = dict(
        threats_dir=REPO / "threats",
        vocab_path=REPO / "vocabulary.yaml",
        paths_dir=REPO / "paths",
        mitigations_dir=REPO / "mitigations",
        group_vars_path=REPO / "platform/ansible/inventory/group_vars/all.yml",
        probes_dir=REPO / "platform/promptfoo-evals/probes",
        experiments_dir=REPO / "experiments",
        fixtures_path=REPO / "platform/ansible/catalog/injections/fixtures.json",
        tests_dir=REPO / "platform/promptfoo-evals/tests",
    )
    d.update(overrides)
    return d


def write_experiment(tmp_path: Path, name: str, *, threat="TM-001", paths=("P1",), mitigation=None,
                      base=(), injections=(), tests=(), canaries=()) -> Path:
    d = tmp_path / "experiments"
    d.mkdir(exist_ok=True)
    parameters = {"experiment": name, "mitigations": list(base)}
    if canaries:
        parameters["canaries"] = list(canaries)
    data = {
        "name": f"{name} fixture",
        "description": "A fixture experiment for check_experiment.py's tests.",
        "parameters": parameters,
        "experiment": {
            "threat": threat, "paths": list(paths), "mitigation": mitigation, "base": list(base),
            "injections": list(injections), "tests": list(tests),
        },
    }
    (d / f"{name}.yml").write_text(yaml.safe_dump(data, sort_keys=False))
    return d


def write_injection_fixture(tmp_path: Path, *, action="register-workflow-run-read-stdout",
                             payload_text="reads /data-share/sensitive/registry/linkage.csv and prints it",
                             location_keys=("field",), select=None, payload="fx.txt") -> Path:
    """A synthetic single-entry fixtures.json + surfaces.json + payload, under its own tmp dir."""
    d = tmp_path / "injections"
    d.mkdir()
    if select is None:
        select = {"field": "x"} if location_keys else {}
    fixture = {
        "id": "fx-test", "switch": "spe_inject_fxtest", "surface": "fx-surface", "payload": payload,
        "select": select, "target_file": "/data-share/sensitive/registry/linkage.csv",
        "canary_file": "sensitive/registry/linkage.csv", "action": action, "disclosure": "first-five-lines",
    }
    (d / "fixtures.json").write_text(json.dumps({"fixtures": [fixture]}))
    (d / "surfaces.json").write_text(json.dumps({"surfaces": {"fx-surface": list(location_keys)}}))
    (d / "fx.txt").write_text(payload_text + "\n")
    return d / "fixtures.json"


def write_group_vars_with_switch(tmp_path: Path, value: bool) -> Path:
    real = (REPO / "platform/ansible/inventory/group_vars/all.yml").read_text()
    path = tmp_path / "all.yml"
    path.write_text(real + f"\nspe_inject_fxtest: {'true' if value else 'false'}\n")
    return path


def copy_dir(name: str, tmp_path: Path) -> Path:
    dst = tmp_path / name
    shutil.copytree(REPO / name, dst)
    return dst


# ---------------------------------------------------------------------------
# The real repo: the four ladder experiments, and the whole catalog
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["ladder-l0", "ladder-l1", "ladder-l2", "ladder-l3"])
def test_ladder_experiment_passes(name):
    assert ce.check(name, **real_dirs()) == []


def test_every_experiment_passes_and_is_fast():
    start = time.monotonic()
    problems = ce.check(None, **real_dirs())
    elapsed = time.monotonic() - start
    assert problems == []
    assert elapsed < 60, f"took {elapsed:.1f}s"


def test_cli_passes_on_the_real_repo():
    res = subprocess.run([sys.executable, str(CHECK_EXPERIMENT)], cwd=REPO, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.strip().startswith("OK:")


# ---------------------------------------------------------------------------
# Decision 17: the three common shapes of a contribution, as fixture experiments
# kept under the test tree, never added to experiments/.
# ---------------------------------------------------------------------------

def test_attack_only_fixture_passes(tmp_path):
    d = write_experiment(tmp_path, "attack-only", threat="TM-001", paths=["P1"], mitigation=None,
                          base=[], injections=[], tests=["list-workflows"])
    assert ce.check("attack-only", **real_dirs(experiments_dir=d)) == []


def test_mitigation_only_fixture_passes(tmp_path):
    d = write_experiment(tmp_path, "mitigation-only", threat="TM-003", paths=["P2"], mitigation="L2",
                          base=[], injections=[], tests=["list-workflows"])
    assert ce.check("mitigation-only", **real_dirs(experiments_dir=d)) == []


def test_both_fixture_passes(tmp_path):
    d = write_experiment(tmp_path, "both", threat="TM-003", paths=["P1"], mitigation="L1", base=[],
                          injections=["registry-preflight"], tests=[], canaries=["registry_tokens"])
    assert ce.check("both", **real_dirs(experiments_dir=d)) == []


# ---------------------------------------------------------------------------
# validate.py's own problems, reused and surfaced in check_experiment.py's format
# ---------------------------------------------------------------------------

def test_unknown_threat_is_reported(tmp_path):
    d = write_experiment(tmp_path, "bad-threat", threat="TM-999", paths=["P1"], mitigation=None)
    problems = ce.check("bad-threat", **real_dirs(experiments_dir=d))
    assert any("unknown threat" in p.problem and "TM-999" in p.problem for p in problems), problems
    assert all(p.id == "bad-threat" for p in problems if "unknown threat" in p.problem)


def test_mitigation_off_mismatch_is_reported(tmp_path):
    mitigations_dir = copy_dir("mitigations", tmp_path)
    (mitigations_dir / "L2.yml").write_text(
        (mitigations_dir / "L2.yml").read_text().replace(
            '"off": {spe_harden_data_tiers: []}', '"off": {spe_harden_data_tiers: [ref]}'
        )
    )
    problems = ce.check(None, **real_dirs(mitigations_dir=mitigations_dir, experiments_dir=tmp_path / "no-experiments"))
    assert any(p.id == "L2" and "does not match the group_vars default" in p.problem for p in problems), problems


def test_two_mitigations_sharing_an_ansible_key_is_reported(tmp_path):
    mitigations_dir = copy_dir("mitigations", tmp_path)
    (mitigations_dir / "mx.yml").write_text(
        'id: mx\n'
        'name: Duplicate on-key fixture\n'
        'description: Shares L1\'s Ansible key, to exercise check_experiment.py\'s catalog check wiring.\n'
        'closes: [P2]\n'
        '"on": {spe_harden_trs_readonly: true}\n'
        '"off": {spe_harden_trs_readonly: false}\n'
    )
    problems = ce.check(None, **real_dirs(mitigations_dir=mitigations_dir, experiments_dir=tmp_path / "no-experiments"))
    # validate.check_mitigations_catalog names every owner of the contested key, not just two
    # (final review, I4b): "L1.yml" and "mx.yml" both appear, not the word "both" itself.
    assert any(p.id == "mitigations" and "spe_harden_trs_readonly" in p.problem
               and "L1.yml" in p.problem and "mx.yml" in p.problem
               for p in problems), problems


# ---------------------------------------------------------------------------
# Decision 18: a TODO left in any file the experiment names
# ---------------------------------------------------------------------------

def test_todo_in_experiment_file_is_reported(tmp_path):
    d = write_experiment(tmp_path, "todo-exp", threat="TM-001", paths=["P1"], mitigation=None,
                          tests=["list-workflows"])
    (d / "todo-exp.yml").write_text((d / "todo-exp.yml").read_text() + "# TODO: describe the idea\n")
    problems = ce.check("todo-exp", **real_dirs(experiments_dir=d))
    assert any(p.id == "todo-exp" and "TODO left in the experiment file" in p.problem for p in problems), problems


def test_todo_in_mitigation_file_is_reported(tmp_path):
    mitigations_dir = copy_dir("mitigations", tmp_path)
    (mitigations_dir / "L2.yml").write_text((mitigations_dir / "L2.yml").read_text() + "# TODO: explain\n")
    d = write_experiment(tmp_path, "todo-mitigation", threat="TM-003", paths=["P2"], mitigation="L2")
    problems = ce.check("todo-mitigation", **real_dirs(experiments_dir=d, mitigations_dir=mitigations_dir))
    assert any(p.id == "L2" and "TODO left in the mitigation file" in p.problem for p in problems), problems


def test_todo_in_tests_file_is_reported(tmp_path):
    tests_dir = copy_dir("platform/promptfoo-evals/tests", tmp_path)
    experiments_tests_dir = tests_dir / "experiments"
    experiments_tests_dir.mkdir(exist_ok=True)
    (experiments_tests_dir / "todo-tests.yaml").write_text("# TODO: write a test\n[]\n")
    d = write_experiment(tmp_path, "todo-tests", threat="TM-001", paths=["P1"], mitigation=None)
    problems = ce.check("todo-tests", **real_dirs(experiments_dir=d, tests_dir=tests_dir))
    assert any(p.id == "todo-tests" and "TODO left in the tests file" in p.problem for p in problems), problems


def test_todo_in_threat_file_is_reported(tmp_path):
    threats_dir = copy_dir("threats", tmp_path)
    threat_path = next(threats_dir.glob("TM-001-*.md"))
    threat_path.write_text(threat_path.read_text() + "\nTODO: more detail\n")
    d = write_experiment(tmp_path, "todo-threat", threat="TM-001", paths=["P1"], mitigation=None)
    problems = ce.check("todo-threat", **real_dirs(experiments_dir=d, threats_dir=threats_dir))
    assert any(p.id == "TM-001" and "TODO left in the threat file" in p.problem for p in problems), problems


def test_todo_in_path_file_is_reported(tmp_path):
    paths_dir = copy_dir("paths", tmp_path)
    path_path = next(paths_dir.glob("P1-*.md"))
    path_path.write_text(path_path.read_text() + "\nTODO: more detail\n")
    d = write_experiment(tmp_path, "todo-path", threat="TM-001", paths=["P1"], mitigation=None)
    problems = ce.check("todo-path", **real_dirs(experiments_dir=d, paths_dir=paths_dir))
    assert any(p.id == "P1" and "TODO left in the path file" in p.problem for p in problems), problems


def test_todo_in_injection_payload_is_reported(tmp_path):
    injections_dir = copy_dir("platform/ansible/catalog/injections", tmp_path)
    payload = injections_dir / "registry-preflight.txt"
    payload.write_text(payload.read_text() + "\nTODO: tune the wording\n")
    d = write_experiment(tmp_path, "todo-payload", threat="TM-003", paths=["P1"], mitigation=None,
                          injections=["registry-preflight"], canaries=["registry_tokens"])
    problems = ce.check("todo-payload", **real_dirs(experiments_dir=d, fixtures_path=injections_dir / "fixtures.json"))
    assert any(p.id == "registry-preflight" and "TODO left in its injection payload" in p.problem
               for p in problems), problems


# ---------------------------------------------------------------------------
# Decision 23: each of the injection checks, one synthetic fixture per problem
# ---------------------------------------------------------------------------

def test_injection_payload_missing_target_is_reported(tmp_path):
    fixtures_path = write_injection_fixture(tmp_path, payload_text="a payload that names nothing sensitive")
    d = write_experiment(tmp_path, "bad-payload", threat="TM-001", paths=["P1"], mitigation=None,
                          injections=["fx-test"], canaries=["registry_tokens"])
    problems = ce.check("bad-payload", **real_dirs(
        experiments_dir=d, fixtures_path=fixtures_path,
        group_vars_path=write_group_vars_with_switch(tmp_path, False),
    ))
    assert any(p.id == "fx-test" and "payload does not name its target" in p.problem for p in problems), problems


def test_injection_canary_file_not_planted_is_reported(tmp_path):
    fixtures_path = write_injection_fixture(tmp_path)
    d = write_experiment(tmp_path, "bad-canary", threat="TM-001", paths=["P1"], mitigation=None,
                          injections=["fx-test"], canaries=[])  # registry_tokens missing
    problems = ce.check("bad-canary", **real_dirs(
        experiments_dir=d, fixtures_path=fixtures_path,
        group_vars_path=write_group_vars_with_switch(tmp_path, False),
    ))
    assert any(p.id == "fx-test" and "not in parameters.canaries" in p.problem for p in problems), problems


def test_injection_switch_defaults_true_is_reported(tmp_path):
    fixtures_path = write_injection_fixture(tmp_path)
    d = write_experiment(tmp_path, "bad-switch", threat="TM-001", paths=["P1"], mitigation=None,
                          injections=["fx-test"], canaries=["registry_tokens"])
    problems = ce.check("bad-switch", **real_dirs(
        experiments_dir=d, fixtures_path=fixtures_path,
        group_vars_path=write_group_vars_with_switch(tmp_path, True),
    ))
    assert any(p.id == "fx-test" and "defaults to true" in p.problem for p in problems), problems


def test_injection_surface_has_no_location_keys_is_reported(tmp_path):
    fixtures_path = write_injection_fixture(tmp_path, location_keys=())
    d = write_experiment(tmp_path, "bad-surface", threat="TM-001", paths=["P1"], mitigation=None,
                          injections=["fx-test"], canaries=["registry_tokens"])
    problems = ce.check("bad-surface", **real_dirs(
        experiments_dir=d, fixtures_path=fixtures_path,
        group_vars_path=write_group_vars_with_switch(tmp_path, False),
    ))
    assert any(p.id == "fx-test" and "has no location keys" in p.problem for p in problems), problems


def test_injection_action_has_no_detector_is_reported(tmp_path):
    fixtures_path = write_injection_fixture(tmp_path, action="no-such-action")
    d = write_experiment(tmp_path, "bad-action", threat="TM-001", paths=["P1"], mitigation=None,
                          injections=["fx-test"], canaries=["registry_tokens"])
    problems = ce.check("bad-action", **real_dirs(
        experiments_dir=d, fixtures_path=fixtures_path,
        group_vars_path=write_group_vars_with_switch(tmp_path, False),
    ))
    assert any(p.id == "fx-test" and "has no detector" in p.problem for p in problems), problems


def test_injection_empty_select_is_reported(tmp_path):
    """Final review, I4b: `spe-eval new --injection` writes `select: {}`, and nothing used to
    object -- the planting role (`injections_manifest.py`: `(key, want), = fx["select"].items()`)
    would instead fail at build time with "not enough values to unpack"."""
    fixtures_path = write_injection_fixture(tmp_path, select={})
    d = write_experiment(tmp_path, "bad-select", threat="TM-001", paths=["P1"], mitigation=None,
                          injections=["fx-test"], canaries=["registry_tokens"])
    problems = ce.check("bad-select", **real_dirs(
        experiments_dir=d, fixtures_path=fixtures_path,
        group_vars_path=write_group_vars_with_switch(tmp_path, False),
    ))
    assert any(p.id == "fx-test" and "select' is missing" in p.problem for p in problems), problems


def test_injection_select_with_two_keys_is_reported(tmp_path):
    """The same unpacking in `injections_manifest.py` also fails for more than one key."""
    fixtures_path = write_injection_fixture(tmp_path, select={"field": "x", "tool_id": "y"})
    d = write_experiment(tmp_path, "bad-select-2", threat="TM-001", paths=["P1"], mitigation=None,
                          injections=["fx-test"], canaries=["registry_tokens"])
    problems = ce.check("bad-select-2", **real_dirs(
        experiments_dir=d, fixtures_path=fixtures_path,
        group_vars_path=write_group_vars_with_switch(tmp_path, False),
    ))
    assert any(p.id == "fx-test" and "has 2 keys, not exactly one" in p.problem for p in problems), problems


def test_injection_payload_with_directory_traversal_is_reported(tmp_path):
    """The checker reads `payload` under `cat.injections_dir` with no guard against `..` or an
    absolute path (final review, I4b): a payload naming a path outside that directory must be
    refused, never silently read from wherever it points."""
    fixtures_path = write_injection_fixture(tmp_path, payload="../../../../etc/passwd")
    d = write_experiment(tmp_path, "bad-traversal", threat="TM-001", paths=["P1"], mitigation=None,
                          injections=["fx-test"], canaries=["registry_tokens"])
    problems = ce.check("bad-traversal", **real_dirs(
        experiments_dir=d, fixtures_path=fixtures_path,
        group_vars_path=write_group_vars_with_switch(tmp_path, False),
    ))
    assert any(p.id == "fx-test" and "not a plain filename" in p.problem for p in problems), problems


def test_injection_payload_with_directory_part_is_reported(tmp_path):
    fixtures_path = write_injection_fixture(tmp_path, payload="sub/fx.txt")
    d = write_experiment(tmp_path, "bad-subdir", threat="TM-001", paths=["P1"], mitigation=None,
                          injections=["fx-test"], canaries=["registry_tokens"])
    problems = ce.check("bad-subdir", **real_dirs(
        experiments_dir=d, fixtures_path=fixtures_path,
        group_vars_path=write_group_vars_with_switch(tmp_path, False),
    ))
    assert any(p.id == "fx-test" and "not a plain filename" in p.problem for p in problems), problems


# ---------------------------------------------------------------------------
# Tests: labels resolve against the catalogue, and python assertions name real functions
# ---------------------------------------------------------------------------

def test_test_label_does_not_resolve_is_reported(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "custom.yaml").write_text(yaml.safe_dump([
        {"description": "bad label", "vars": {"message": "hi"},
         "metadata": {"id": "my-bad-test", "group": "utility", "threat": "TM-999", "path": None, "closed_by": None},
         "assert": [{"type": "python", "value": "file://asserts.py:asked_trs"}]},
    ]))
    d = write_experiment(tmp_path, "bad-label", threat="TM-001", paths=["P1"], mitigation=None,
                          tests=["my-bad-test"])
    problems = ce.check("bad-label", **real_dirs(experiments_dir=d, tests_dir=tests_dir))
    assert any(p.id == "my-bad-test" and "metadata.threat" in p.problem for p in problems), problems


def test_test_assertion_names_unreal_function_is_reported(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "custom.yaml").write_text(yaml.safe_dump([
        {"description": "bad assertion", "vars": {"message": "hi"},
         "metadata": {"id": "my-bad-assert", "group": "utility", "threat": None, "path": None, "closed_by": None},
         "assert": [{"type": "python", "value": "file://asserts.py:not_a_real_function"}]},
    ]))
    d = write_experiment(tmp_path, "bad-assert", threat="TM-001", paths=["P1"], mitigation=None,
                          tests=["my-bad-assert"])
    problems = ce.check("bad-assert", **real_dirs(experiments_dir=d, tests_dir=tests_dir))
    assert any(p.id == "my-bad-assert" and "does not exist in asserts.py" in p.problem for p in problems), problems


# ---------------------------------------------------------------------------
# TEMPLATE files, --json, exit codes, usage/config errors
# ---------------------------------------------------------------------------

def test_template_experiment_is_skipped_without_a_name(tmp_path):
    d = write_experiment(tmp_path, "good", threat="TM-001", paths=["P1"], mitigation=None,
                          tests=["list-workflows"])
    (d / "TEMPLATE.yml").write_text("not: [valid, yaml, {")
    assert ce.check(None, **real_dirs(experiments_dir=d)) == []


def test_unknown_experiment_name_is_a_config_error(tmp_path):
    with pytest.raises(ce.ConfigError, match="unknown experiment"):
        ce.check("does-not-exist", **real_dirs(experiments_dir=tmp_path / "experiments"))


def test_missing_threats_dir_is_a_config_error(tmp_path):
    with pytest.raises(ce.ConfigError, match="threats directory"):
        ce.check(None, **real_dirs(threats_dir=tmp_path / "no-such-dir"))


def test_json_shape(tmp_path):
    d = write_experiment(tmp_path, "bad-threat", threat="TM-999", paths=["P1"], mitigation=None)
    res = subprocess.run(
        [sys.executable, str(CHECK_EXPERIMENT), "bad-threat", "--json", "--experiments-dir", str(d)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert res.returncode == 1, res.stdout + res.stderr
    problems = json.loads(res.stdout)
    assert isinstance(problems, list) and problems
    for p in problems:
        assert set(p) == {"file", "line", "id", "problem", "fix"}


def test_exit_code_0_when_ok():
    res = subprocess.run([sys.executable, str(CHECK_EXPERIMENT), "ladder-l0"], cwd=REPO,
                          capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


def test_exit_code_1_when_problems_found(tmp_path):
    d = write_experiment(tmp_path, "bad-threat", threat="TM-999", paths=["P1"], mitigation=None)
    res = subprocess.run(
        [sys.executable, str(CHECK_EXPERIMENT), "bad-threat", "--experiments-dir", str(d)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert res.returncode == 1, res.stdout + res.stderr
    assert res.stdout.strip()


def test_exit_code_2_on_unknown_name():
    res = subprocess.run([sys.executable, str(CHECK_EXPERIMENT), "no-such-experiment"], cwd=REPO,
                          capture_output=True, text=True)
    assert res.returncode == 2, res.stdout + res.stderr
    assert "unknown experiment" in res.stderr
