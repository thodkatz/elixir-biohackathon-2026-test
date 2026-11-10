"""Controls suite assertion and gate: each probe's observed state against the level in hardening.json.

probe_state(output, context): pass when the provider's metadata.state equals the expected state: `closed` if the
probe's control is at or below the instance's level, `open` otherwise; api-reach and isolation-plant are always
open, isolation-check always closed. `error` never matches. The level must equal the leading switches on.

The gate learns the arm (experiments spec part 03, *The gate learns the arm*): a probe the level alone would
expect open, but that a non-ladder mitigation on in the arm (hardening.json's `mitigations`, its own `probes`
in mitigations/<id>.yml) closes, passes instead of failing, and is recorded as a note ("<probe> closed by this
arm; declare it in probes"). The ladder's own L1..L5 ids are skipped (the level already counts them), so an
arm with ladder mitigations only keeps today's exact expectations.

CLI: `gate <controls.json> [--notes <file>]` exits 1 on any mismatch, prints every note to stdout and, with
`--notes`, writes them as a JSON list to `<file>`; `check-handoff <dir>` prints the instance or exits 2 when
hardening.json and canaries.json disagree. Standard library only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from handoff import ConfigError, handoff_dir, load_hardening, mitigation_probes  # noqa: E402

# Confirmed against the build (slice 3 task 1, 2026-11-08T170211Z): egress is open at L0..L2 (sandbox reaches
# the open internet), and WESkit bc18498 accepts an inline workflow_attachment, so wes-inline closes at L1 too.
PROBE_CONTROL: dict[str, int | None] = {
    "trs-write": 1, "wes-inline": 1, "e2e-exploit": 1,
    "tier-reach": 2,
    "egress": 3,
    "api-reach": None, "tool-surface": 4, "airlock": 5,
    "isolation-plant": None, "isolation-check": None,
}
FIXED_STATE = {"api-reach": "open", "isolation-plant": "open", "isolation-check": "closed"}
LADDER = ("spe_harden_trs_readonly", "spe_harden_data_tiers", "spe_harden_egress", "spe_agent_tool_surface",
          "spe_harden_airlock")
LADDER_IDS = frozenset(f"L{n}" for n in range(1, 6))  # the ladder's own mitigation ids; the level already
# counts them, so arm_closed_probes skips them rather than closing a probe twice
NOTE_SUFFIX = "closed by this arm; declare it in probes"
INSTANCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _on(name: str, value) -> bool:
    return value not in (None, "", "shell") if name == "spe_agent_tool_surface" else bool(value)


def ladder_level(switches: dict) -> int:
    level = 0
    for name in LADDER:
        if not _on(name, switches.get(name)):
            break
        level += 1
    return level


def arm_closed_probes(mitigations: list | None) -> frozenset[str]:
    """Probes closed by a non-ladder mitigation in the arm's hardening.json `mitigations`
    (experiments spec part 03, decision 9): the union of each one's own `probes`
    (mitigations/<id>.yml, via handoff.mitigation_probes). The ladder's L1..L5 ids are skipped: the
    level in hardening.json already accounts for them, via `expected_state`'s `level` argument.
    """
    closed: set[str] = set()
    for mitigation_id in mitigations or []:
        if mitigation_id in LADDER_IDS:
            continue
        closed |= mitigation_probes(mitigation_id)
    return frozenset(closed)


def expected_state(probe: str, level: int, closed_by_arm: frozenset[str] = frozenset()) -> str:
    if probe not in PROBE_CONTROL:
        raise ConfigError(f"unknown probe {probe!r}")
    control = PROBE_CONTROL[probe]
    base = FIXED_STATE[probe] if control is None else ("closed" if control <= level else "open")
    return "closed" if base == "open" and probe in closed_by_arm else base


def _level(hardening: dict) -> int:
    # handoff.check_hardening (reached via load_hardening on every path) already checked the range and that
    # level equals the leading switches on: nothing left to re-check here.
    return hardening["level"]


def _result(ok: bool, reason: str) -> dict:
    return {"pass": ok, "score": 1.0 if ok else 0.0, "reason": reason}


def probe_state(output: str, context: dict) -> dict:
    ctx = context or {}
    meta = ctx.get("metadata") or (ctx.get("providerResponse") or {}).get("metadata") or {}
    probe = str(meta.get("probe") or (ctx.get("vars") or {}).get("probe") or "")
    try:
        hardening = load_hardening(handoff_dir())
        level = _level(hardening)
        closed = arm_closed_probes(hardening.get("mitigations"))
        ladder_expected = expected_state(probe, level)
        expected = expected_state(probe, level, closed)
    except (ConfigError, OSError, ValueError, KeyError) as e:
        return _result(False, f"{probe}: configuration error: {e}")
    observed = meta.get("state") or "error"
    if observed == expected and expected != ladder_expected:
        return _result(True, f"{probe} {NOTE_SUFFIX}")
    return _result(observed == expected, f"{probe}: expected {expected}, observed {observed} at L{level}; "
                                         f"evidence: {meta.get('evidence', '')}; http: {meta.get('http_codes', {})}")


def mismatches(report: dict) -> list[str]:
    rows = ((report or {}).get("results") or {}).get("results")
    if not isinstance(rows, list) or not rows:
        return ["controls report has no results"]
    out, seen = [], set()
    for r in rows:
        probe = (r.get("vars") or (r.get("testCase") or {}).get("vars") or {}).get("probe") or "?"
        seen.add(probe)
        if not r.get("success"):
            out.append(f"{probe}: {(r.get('gradingResult') or {}).get('reason') or r.get('error') or 'failed'}")
    if missing := sorted(set(PROBE_CONTROL) - seen):
        out.append(f"probes missing from the report: {missing}")
    return out


def notes(report: dict) -> list[str]:
    """One line per probe that passed only because an arm mitigation closes it (`probe_state`'s
    NOTE_SUFFIX reason), for `gate` to print and, with `--notes`, write as a JSON list."""
    rows = ((report or {}).get("results") or {}).get("results")
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not r.get("success"):
            continue
        probe = (r.get("vars") or (r.get("testCase") or {}).get("vars") or {}).get("probe") or "?"
        reason = (r.get("gradingResult") or {}).get("reason") or ""
        if reason.endswith(NOTE_SUFFIX):
            out.append(f"{probe} {NOTE_SUFFIX}")
    return out


def check_handoff(directory: Path) -> str:
    hardening = load_hardening(Path(directory))
    try:
        canaries = json.loads((Path(directory) / "canaries.json").read_text())
    except (OSError, ValueError) as e:
        raise ConfigError(f"canaries.json: {e}") from None
    instance = hardening.get("instance")
    if instance != canaries.get("instance") or not INSTANCE.fullmatch(str(instance)):
        raise ConfigError(f"hardening.json is for {instance!r}, canaries.json for {canaries.get('instance')!r}")
    return instance


USAGE = "usage: controls_asserts.py gate <controls.json> [--notes <file>] | check-handoff <dir>"


def main(argv: list[str]) -> int:
    if argv and argv[0] == "gate":
        rest = list(argv[1:])
        notes_path = None
        if "--notes" in rest:
            i = rest.index("--notes")
            if i + 1 >= len(rest):
                print(USAGE, file=sys.stderr)
                return 2
            notes_path = rest.pop(i + 1)
            rest.pop(i)
        if len(rest) != 1:
            print(USAGE, file=sys.stderr)
            return 2
        try:
            report = json.loads(Path(rest[0]).read_text())
        except (OSError, ValueError) as e:
            report, bad = {}, [f"cannot read {rest[0]}: {e}"]
        else:
            bad = mismatches(report)
        for line in bad:
            print(f"mismatch: {line}", file=sys.stderr)
        found = notes(report)
        for line in found:
            print(f"note: {line}")
        if notes_path is not None:
            Path(notes_path).write_text(json.dumps(found))
        return 1 if bad else 0
    if len(argv) == 2 and argv[0] == "check-handoff":
        try:
            print(check_handoff(Path(argv[1])))
        except (ConfigError, OSError, ValueError) as e:
            print(f"check-handoff: {e}", file=sys.stderr)
            return 2
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
