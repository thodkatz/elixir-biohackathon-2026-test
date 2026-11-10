"""platform/instance/spe_eval.py: experiments, arms, the suite config, run id/reports layout and
the lock (experiments spec part 03, `docs/specs/2026-11-10-experiments-design/03-evaluation-in-
workspace.md`, decisions 7, 9 and 11). Arm and creation-time tests read the repository's own
`experiments/`/`mitigations/` files (the ladder), as `test_ladder_experiments.py` does, so they
exercise the real catalogue rather than a copy that could drift from it.
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "platform" / "instance"))
import spe_eval  # noqa: E402


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


# --- which experiment / arms ------------------------------------------------------------------

def test_load_experiment_reads_the_real_file():
    experiment = spe_eval.load_experiment("ladder-l2")
    assert experiment["parameters"]["experiment"] == "ladder-l2"
    assert experiment["experiment"]["mitigation"] == "L2"


def test_load_experiment_missing_file_is_a_config_error():
    with pytest.raises(spe_eval.ConfigError):
        spe_eval.load_experiment("no-such-experiment")


def test_load_local_vars_reads_instances_local_yml(tmp_path):
    instances = tmp_path / "platform" / "ansible" / "instances"
    instances.mkdir(parents=True)
    (instances / "local.yml").write_text("spe_experiment: ladder-l2\nspe_instance: t-01\n")
    local_vars = spe_eval.load_local_vars(tmp_path)
    assert local_vars == {"spe_experiment": "ladder-l2", "spe_instance": "t-01"}


def test_load_local_vars_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(spe_eval.ConfigError, match="local re-apply"):
        spe_eval.load_local_vars(tmp_path)


def test_default_experiment_name_reads_spe_experiment():
    assert spe_eval.default_experiment_name({"spe_experiment": "ladder-l2"}) == "ladder-l2"


def test_default_experiment_name_missing_is_a_config_error():
    with pytest.raises(spe_eval.ConfigError, match="spe_experiment"):
        spe_eval.default_experiment_name({})


@pytest.mark.parametrize("name,arms", [
    ("ladder-l0", ("baseline",)),
    ("ladder-l1", ("baseline", "mitigated")),
    ("ladder-l2", ("baseline", "mitigated")),
    ("ladder-l3", ("baseline", "mitigated")),
])
def test_experiment_arms(name, arms):
    assert spe_eval.experiment_arms(spe_eval.load_experiment(name)) == arms


def test_arm_mitigations_ladder_l2():
    experiment = spe_eval.load_experiment("ladder-l2")
    assert spe_eval.arm_mitigations(experiment, "baseline") == ["L1"]
    assert spe_eval.arm_mitigations(experiment, "mitigated") == ["L1", "L2"]


def test_arm_mitigations_unknown_arm_raises():
    experiment = spe_eval.load_experiment("ladder-l0")  # one arm only
    with pytest.raises(ValueError, match="mitigated"):
        spe_eval.arm_mitigations(experiment, "mitigated")


# --- arm_vars (decision 9) ----------------------------------------------------------------------

def test_arm_vars_ladder_l2_baseline_is_l1_on_l2_l3_off():
    values = spe_eval.arm_vars(spe_eval.load_experiment("ladder-l2"), "baseline")
    assert values["spe_harden_trs_readonly"] is True       # L1 on
    assert values["spe_harden_data_tiers"] == []            # L2 off
    assert values["spe_harden_egress"] is False             # L3 off
    assert values["spe_mitigations"] == ["L1"]
    assert values["spe_experiment"] == "ladder-l2"


def test_arm_vars_ladder_l2_mitigated_is_l1_and_l2_on():
    values = spe_eval.arm_vars(spe_eval.load_experiment("ladder-l2"), "mitigated")
    assert values["spe_harden_trs_readonly"] is True
    assert values["spe_harden_data_tiers"] == ["ref", "genomes"]
    assert values["spe_harden_egress"] is False              # L3 still off: not in base or under test
    assert values["spe_mitigations"] == ["L1", "L2"]


def test_arm_vars_ladder_l0_one_arm_every_mitigation_off():
    values = spe_eval.arm_vars(spe_eval.load_experiment("ladder-l0"), "baseline")
    assert values["spe_harden_trs_readonly"] is False
    assert values["spe_harden_data_tiers"] == []
    assert values["spe_harden_egress"] is False
    assert values["spe_mitigations"] == []
    assert values["spe_experiment"] == "ladder-l0"


def test_arm_vars_mitigation_outside_the_experiment_is_off_in_both_arms():
    # ladder-l1 names only L1; L2 and L3 stay off in both arms, whatever a participant also
    # selected on the creation form (decision 9's acceptance): arm_vars never looks at the
    # running build at all, only at the experiment file and the mitigation catalogue.
    experiment = spe_eval.load_experiment("ladder-l1")
    for arm in spe_eval.experiment_arms(experiment):
        values = spe_eval.arm_vars(experiment, arm)
        assert values["spe_harden_data_tiers"] == []     # L2 off
        assert values["spe_harden_egress"] is False       # L3 off


def test_arm_vars_injection_switches_are_the_same_in_both_arms():
    experiment = spe_eval.load_experiment("ladder-l2")
    baseline = spe_eval.arm_vars(experiment, "baseline")
    mitigated = spe_eval.arm_vars(experiment, "mitigated")
    switches = ["spe_inject_trs_description", "spe_inject_drs_description", "spe_inject_workflow_comment"]
    for switch in switches:
        assert baseline[switch] is True   # ladder-l2 lists all three injections
        assert baseline[switch] == mitigated[switch]


def test_write_json_round_trips(tmp_path):
    values = {"spe_mitigations": ["L1"], "spe_harden_trs_readonly": True}
    path = spe_eval.write_json(values, tmp_path / "arm" / "vars.json")
    assert path.exists()
    import json
    assert json.loads(path.read_text()) == values


# --- creation-time check (decision 7) ------------------------------------------------------------

def matching_local_vars(experiment: dict) -> dict:
    """A `local.yml` that matches `experiment`'s `parameters` and `vars` exactly."""
    params = experiment["parameters"]
    all_canary_types = ["registry_tokens", "honeypot_files", "vcf_variants", "flag_file",
                         "drs_metadata", "trs_descriptions", "workflow_comments", "service_info"]
    local_vars = {
        "spe_samples": params["samples"],
        "spe_tiers": params["tiers"],
        "spe_workflows": params["workflows"],
        "spe_run_smoke_test": params["smoke_test"],
        **{f"spe_canary_{t}": (t in params["canaries"]) for t in all_canary_types},
        **(experiment.get("vars") or {}),
    }
    return local_vars


def test_check_creation_time_no_mismatch_when_the_build_matches():
    experiment = spe_eval.load_experiment("ladder-l0")
    assert spe_eval.check_creation_time(experiment, matching_local_vars(experiment)) == []
    spe_eval.check_build_matches(experiment, matching_local_vars(experiment))  # does not raise


def test_check_creation_time_names_every_differing_key():
    experiment = spe_eval.load_experiment("ladder-l0")
    local_vars = matching_local_vars(experiment)
    local_vars["spe_tiers"] = ["ref"]                       # a parameter key, differs
    local_vars["spe_canary_flag_file"] = not local_vars["spe_canary_flag_file"]  # a canaries key, differs
    local_vars["spe_eval_sink"] = not local_vars["spe_eval_sink"]  # a vars key, differs
    mismatches = spe_eval.check_creation_time(experiment, local_vars)
    assert mismatches == sorted(["spe_tiers", "spe_canary_flag_file", "spe_eval_sink"])


def test_check_creation_time_list_params_are_order_insensitive():
    # task 3 review, minor 1: spe_samples/spe_tiers/spe_workflows differing only in order (a build
    # whose form held the experiment's own set in a different order) is not a false mismatch.
    experiment = spe_eval.load_experiment("ladder-l0")
    local_vars = matching_local_vars(experiment)
    local_vars["spe_tiers"] = list(reversed(local_vars["spe_tiers"]))
    local_vars["spe_workflows"] = list(reversed(local_vars["spe_workflows"]))
    assert local_vars["spe_tiers"] != experiment["parameters"]["tiers"]  # reordered, not equal
    assert spe_eval.check_creation_time(experiment, local_vars) == []
    spe_eval.check_build_matches(experiment, local_vars)  # does not raise


def test_check_creation_time_skips_flavor_which_local_yml_never_holds():
    # spe_flavor is VM sizing, done once at creation: it is not in spe_local_vars, so a local.yml
    # with no such key at all must not be reported as a mismatch.
    experiment = spe_eval.load_experiment("ladder-l0")
    assert "flavor" in experiment["parameters"]
    local_vars = matching_local_vars(experiment)
    assert "spe_flavor" not in local_vars
    assert spe_eval.check_creation_time(experiment, local_vars) == []


def test_check_creation_time_excludes_experiment_and_mitigations():
    experiment = spe_eval.load_experiment("ladder-l2")
    local_vars = matching_local_vars(experiment)
    local_vars["spe_experiment"] = "some-other-experiment"
    local_vars["spe_mitigations"] = ["L3"]
    assert spe_eval.check_creation_time(experiment, local_vars) == []


def test_check_build_matches_raises_config_error_naming_the_keys():
    experiment = spe_eval.load_experiment("ladder-l0")
    local_vars = matching_local_vars(experiment)
    local_vars["spe_tiers"] = ["ref"]
    with pytest.raises(spe_eval.ConfigError, match="spe_tiers"):
        spe_eval.check_build_matches(experiment, local_vars)


# --- the suite (R1) --------------------------------------------------------------------------

def test_suite_config_with_no_tests_returns_agent_yaml_unchanged():
    experiment = spe_eval.load_experiment("ladder-l0")  # tests: []
    path = spe_eval.suite_config(experiment, Path("/does/not/matter"))
    assert path == REPO / "platform" / "promptfoo-evals" / "agent.yaml"
    assert path.exists()


def test_suite_config_with_named_tests_plus_utility_group(tmp_path):
    experiment = {"experiment": {"tests": ["summarise-workflows"], "injections": []}}
    out = spe_eval.suite_config(experiment, tmp_path)
    assert out == tmp_path / "suite.yaml"
    config = load_yaml(out)
    ids = [t["metadata"]["id"] for t in config["tests"]]
    assert ids[0] == "summarise-workflows"          # the named test first
    assert "list-workflows" in ids                   # a utility test, not named, pulled in
    assert "inventory-drs" in ids                     # another utility test
    # Every utility test is present (R1: "plus every test of the utility group").
    utility_file = REPO / "platform" / "promptfoo-evals" / "tests" / "utility.yaml"
    utility_cases = yaml.safe_load(utility_file.read_text())
    utility_ids = {c["metadata"]["id"] for c in utility_cases}
    assert utility_ids <= set(ids)
    # Paths made absolute, so the suite runs from any directory (R1).
    assert config["providers"][0]["id"] == f"file://{REPO / 'platform/promptfoo-evals/agui_provider.py'}"


def test_suite_config_unknown_test_id_is_a_config_error(tmp_path):
    experiment = {"experiment": {"tests": ["no-such-test"]}}
    with pytest.raises(spe_eval.ConfigError, match="no-such-test"):
        spe_eval.suite_config(experiment, tmp_path)


# --- run id, home, reports layout ---------------------------------------------------------------

def test_run_id_format():
    assert re.fullmatch(r"\d{8}T\d{6}Z", spe_eval.run_id())


def test_spe_eval_home_and_reports_dir(tmp_path):
    home = spe_eval.spe_eval_home(tmp_path)
    assert home == tmp_path / "spe-eval"
    reports = spe_eval.reports_dir("ladder-l2", "20261110T120000Z", "baseline", tmp_path)
    assert reports == tmp_path / "spe-eval" / "reports" / "ladder-l2" / "20261110T120000Z" / "baseline"


# --- the lock (decision 11) -------------------------------------------------------------------

def test_lock_holder_is_none_without_a_lock_file(tmp_path):
    assert spe_eval.Lock(tmp_path / "lock").holder() is None


def test_lock_second_acquire_refuses_naming_the_holder(tmp_path):
    path = tmp_path / "lock"
    first = spe_eval.Lock(path)
    first.acquire("20261110T120000Z")
    try:
        second = spe_eval.Lock(path)
        with pytest.raises(spe_eval.LockHeld) as exc_info:
            second.acquire("20261110T130000Z")
        assert exc_info.value.token == "20261110T120000Z"
        assert "20261110T120000Z" in str(exc_info.value)
    finally:
        first.release()


def test_lock_release_lets_another_acquire(tmp_path):
    path = tmp_path / "lock"
    first = spe_eval.Lock(path)
    first.acquire("tok-1")
    first.release()
    second = spe_eval.Lock(path)
    second.acquire("tok-2")
    assert second.holder() == "tok-2"
    second.release()
