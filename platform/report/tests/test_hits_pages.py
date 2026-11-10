"""hits_view.py: the participant page's body and a standalone HTML document (spec *Participant
page*; decisions 4, 5, 11). Hit dicts here are hand-built to the schema in canary_hits.hits_for,
not read from fixtures, since these tests check rendering only. Tokens are made-up
(FCANARY-TEST01)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hits_view  # noqa: E402
from hits_view import NOTICE, participant_body, standalone  # noqa: E402

META = {"workspace": "6f1c2a9e-3b7d-4e1a-9c2f-0a1b2c3d4e5f", "instance": "fixture", "owner": "alice"}


def hit(kind: str, place: str, **fields) -> dict:
    base = {
        "id": 1, "detected": "2026-11-10T14:03:07Z", "at": "2026-11-10T14:03:05Z",
        "workspace": META["workspace"], "instance": META["instance"], "owner": META["owner"],
        "frontend": "agui", "source": "agui-journal",
        "session": {"id": "s1", "title": "Variant QC"}, "run": "r1",
        "prompt": "Summarise the variants", "kind": kind, "place": place, "tool": None,
        "canary": {"type": "vcf-canary-variant", "file": "sensitive/genomes/truth.vcf.gz",
                   "token": "FCANARY-TEST01"},
        "excerpt": {"text": "chr1 10583 FCANARY-TEST01 G A", "start": 11, "end": 25},
    }
    return base | fields


def test_notice_on_participant_page():
    body = participant_body(META, [], None)
    assert NOTICE in body


def test_counts_loud_and_quiet():
    hits = (
        [hit("touched", "tool_result") for _ in range(2)]
        + [hit("answer", "answer")]
        + [hit("seen", "tool_result") for _ in range(3)]
    )
    body = participant_body(META, hits, None)
    assert "3 leaks" in body
    assert "also seen: 3" in body


def test_frontend_labels():
    hits = [hit("touched", "tool_result", frontend="agui"),
            hit("touched", "tool_result", frontend="openwebui")]
    body = participant_body(META, hits, None)
    assert "AG-UI" in body
    assert "Open WebUI" in body


def test_value_marked():
    body = participant_body(META, [hit("touched", "tool_result")], None)
    assert "<mark>FCANARY-TEST01</mark>" in body


def test_escapes_fields():
    hits = [hit("answer", "answer", session={"id": "s1", "title": "<script>x</script>"})]
    body = participant_body(META, hits, None)
    assert "<script>x</script>" not in body
    assert "&lt;script&gt;x&lt;/script&gt;" in body


def test_standalone_has_no_script_and_inlines_css():
    body = participant_body(META, [hit("touched", "tool_result")], None)
    doc = standalone("Canary hits", body)
    assert "<script" not in doc
    assert "<style>" in doc
    assert "<mark>FCANARY-TEST01</mark>" in doc


def test_archived_status_none_says_archived():
    body = participant_body(META, [], None)
    assert "archived" in body.lower()
