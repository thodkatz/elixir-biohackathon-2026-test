"""Decision 8 (experiments spec part 03, *The hand-off on the VM*): neither `~/spe-eval`
(`spe_eval_dir`: the VM-local hand-off and spe-eval's own reports) nor
`platform/ansible/instances/local.yml` (the seed, from which every canary follows) is ever mounted
into a container -- the agent's own sandbox reaches neither; Node, promptfoo and `uv` run on the
VM host itself for exactly this reason (the `spe_eval` role). A grep-style check over every compose
file and compose template in the repository, so a volume added to one of them later is caught here
rather than only by reading the spec.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

COMPOSE_FILES = sorted({
    *((REPO / "platform" / "instance").glob("compose*.yml")),
    *((REPO / "platform" / "ansible" / "roles").glob("*/templates/*compose*.y*ml.j2")),
    *((REPO / "platform" / "ansible" / "roles").glob("*/templates/*compose*.y*ml")),
})

# "/spe-eval/" (trailing slash) rather than "spe-eval" alone, so this never flags the unrelated
# spe-eval-sink test receiver fixture (platform/instance/compose.eval-sink.yml, /var/lib/spe-eval-sink).
FORBIDDEN = ("spe_eval_dir", "~/spe-eval", "/spe-eval/", "instances/local.yml")


def test_at_least_the_known_compose_files_are_checked():
    # A regression on this list itself (a new compose file added under a name this glob misses)
    # would silently check nothing; pin the count of what this repository has today.
    names = {p.relative_to(REPO).as_posix() for p in COMPOSE_FILES}
    assert names == {
        "platform/instance/compose.egress.yml",
        "platform/instance/compose.eval-sink.yml",
        "platform/instance/compose.yml",
        "platform/ansible/roles/eval_sink/templates/docker-compose.yml.j2",
        "platform/ansible/roles/workflow_stack/templates/compose.install.yaml.j2",
    }, names


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_compose_file_mounts_spe_eval_or_local_yml(path):
    text = path.read_text()
    hits = [needle for needle in FORBIDDEN if needle in text]
    assert not hits, f"{path}: mentions {hits} (decision 8: neither may reach a container)"
