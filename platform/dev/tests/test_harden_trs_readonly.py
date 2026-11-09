"""spe_harden_trs_readonly (L1): TRS read-only for the sandbox; operator writes via 127.0.0.1 only."""
import yaml

from ansible_render import GOLDEN, load_vars, render

ON = {"spe_harden_trs_readonly": True}


def compose(**sw):
    return yaml.safe_load(render("workflow_stack", "compose.install.yaml.j2", **sw))


def labels(svc):
    return dict(lab.split("=", 1) for lab in svc["labels"])


def test_off_renders_todays_compose_and_weskit_config():
    assert render("workflow_stack", "compose.install.yaml.j2") == (GOLDEN / "compose.install.L0.yaml").read_text()
    assert render("workflow_stack", "weskit_config.yaml.j2") == (GOLDEN / "weskit_config.L0.yaml").read_text()


def test_on_public_trs_router_reads_only_and_writes_are_refused():
    lab = labels(compose(**ON)["services"]["trs-filer"])
    assert lab["traefik.http.routers.trs.rule"] == 'PathPrefix("/ga4gh/trs") && Method("GET", "HEAD")'
    assert lab["traefik.http.routers.trs-deny.rule"] == 'PathPrefix("/ga4gh/trs") && !Method("GET", "HEAD")'
    assert lab["traefik.http.routers.trs-deny.entrypoints"] == "websecure"
    assert lab["traefik.http.routers.trs-deny.middlewares"] == "trs-deny"
    assert lab["traefik.http.middlewares.trs-deny.ipwhitelist.sourcerange"] == "192.0.2.1/32"
    assert lab["traefik.http.routers.trs-admin.rule"] == 'PathPrefix("/ga4gh/trs")'
    assert lab["traefik.http.routers.trs-admin.entrypoints"] == "admin"
    assert {lab[f"traefik.http.routers.{r}.service"] for r in ("trs", "trs-deny", "trs-admin")} == {"trs"}


def test_on_admin_entrypoint_is_published_on_localhost_only():
    t = compose(**ON)["services"]["traefik"]
    assert "--entrypoints.admin.address=:8443" in t["command"]
    assert t["ports"] == ["443:443", "127.0.0.1:8443:8443"]


def test_operator_trs_writes_follow_the_switch():
    assert load_vars()["spe_trs_write_api"] == "https://10.0.2.245/ga4gh/trs/v2"
    assert load_vars(**ON)["spe_trs_write_api"] == "https://127.0.0.1:8443/ga4gh/trs/v2"
