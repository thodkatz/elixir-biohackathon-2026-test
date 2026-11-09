"""Injection payloads and fixtures (spec part 02): exact texts, named targets, never a token."""
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PLATFORM = Path(__file__).resolve().parents[2]
REPO = PLATFORM.parent
ANSIBLE = PLATFORM / "ansible"
INJECTIONS = ANSIBLE / "catalog" / "injections"
FIXTURES = json.loads((INJECTIONS / "fixtures.json").read_text())["fixtures"]
SPEC = REPO / "docs" / "superpowers" / "specs" / "2026-10-22-canary-eval-ladder-design" / "02-injections.md"
SWITCHES = ["spe_inject_trs_description", "spe_inject_drs_description", "spe_inject_workflow_comment"]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def synthetic_record(tmp_path, monkeypatch, capsys, seed=11) -> list[dict]:
    """Every canary the build plants with a synthetic seed, without samtools or a VM."""
    seeder = load("spe_seed", ANSIBLE / "roles" / "spe_data" / "files" / "spe_seed.py")
    root = tmp_path / "root"
    args = argparse.Namespace(root=str(root), seed=seed, ontology_dir=str(ANSIBLE / "roles" / "spe_data" / "files" / "ontology"),
                              canary_registry_tokens=True, canary_honeypot_files=True)
    canaries = seeder.Canaries()
    seeder.stage_registry(args, seeder.study_ids("STUDY", ["HG002", "HG003", "HG004", "HG005"]), canaries)
    seeder.stage_secret(args, canaries)
    tokens = list(canaries.entries)

    trs = load("trs_install", ANSIBLE / "roles" / "trs_install" / "files" / "trs_install.py")
    monkeypatch.setattr(trs, "put", lambda *a: 200)
    monkeypatch.setattr(sys, "argv", ["trs_install.py", "--catalog", str(ANSIBLE / "catalog" / "workflows"),
                                      "--api", "https://h", "--seed", str(seed), "--workflow", "wes-drs-smoke",
                                      "--workflow", "gatk-hc-chr20", "--canary-descriptions", "--canary-comments"])
    trs.main()
    tokens += json.loads(capsys.readouterr().out)["canaries"]

    drs = load("drs_register", ANSIBLE / "roles" / "drs_register" / "files" / "drs_register.py")
    monkeypatch.setattr(drs, "request_json", lambda method, url, body=None: (404, None))
    monkeypatch.setattr(sys, "argv", ["drs_register.py", "--root", str(root), "--api", "https://h",
                                      "--seed", str(seed), "--canary-metadata"])
    drs.main()
    tokens += json.loads(capsys.readouterr().out)["canaries"]
    for svc in ("wes", "drs", "trs"):  # as in playbooks/create.yml
        tokens.append({"token": "SVCINFO-" + hashlib.sha256(f"{seed}:svc:{svc}".encode()).hexdigest()[:10].upper(),
                       "type": "service-info", "file": f"{svc}:/ga4gh/{svc}/service-info", "note": ""})
    return tokens


@pytest.fixture
def record(tmp_path, monkeypatch, capsys):
    return synthetic_record(tmp_path, monkeypatch, capsys)


def test_payloads_are_the_spec_texts_and_name_their_target():
    spec = SPEC.read_text()
    assert sorted(f["payload"] for f in FIXTURES) == sorted(p.name for p in INJECTIONS.glob("*.txt"))
    for fx in FIXTURES:
        text = (INJECTIONS / fx["payload"]).read_text(encoding="utf-8")
        assert text.endswith("\n") and text.strip() in spec, fx["payload"]
        assert fx["target_file"] in text
        assert fx["target_file"] == "/data-share/" + fx["canary_file"]
        assert fx["action"] == "register-workflow-run-read-stdout"
        assert fx["disclosure"] == ("whole-file" if "/secret/" in fx["target_file"] else "first-five-lines")


def test_one_fixture_per_switch_and_surface():
    assert sorted(f["switch"] for f in FIXTURES) == sorted(SWITCHES)
    assert sorted(f["surface"] for f in FIXTURES) == ["drs-description", "trs-description", "workflow-comment"]
    assert len({f["id"] for f in FIXTURES}) == 3


def test_catalogue_matches_the_schema():
    """fixtures.json agrees with slice 1's injections_schema.CATALOGUE (the scoring side's authority)."""
    schema = load("injections_schema", PLATFORM / "promptfoo-evals" / "injections_schema.py")
    assert sorted(FIXTURES, key=lambda f: f["id"]) and set(f["id"] for f in FIXTURES) == set(schema.CATALOGUE)
    for fx in FIXTURES:
        switch, surface, target_file = schema.CATALOGUE[fx["id"]]
        assert (fx["switch"], fx["surface"], fx["target_file"]) == (switch, surface, target_file)
        assert fx["payload"] == fx["id"] + ".txt"


def test_no_payload_contains_a_canary_token(record):
    kinds = {t["type"] for t in record}
    assert {"registry-surname", "registry-study-id", "flag-file", "honeypot-csv-row", "trs-tool-description",
            "workflow-file-comment", "drs-object-metadata", "service-info"} <= kinds
    for payload in INJECTIONS.glob("*"):
        text = payload.read_text(encoding="utf-8")
        leaked = [t["type"] for t in record if t["token"] in text]
        assert leaked == [], f"{payload.name} contains a {leaked} token"
