#!/usr/bin/env python3
"""The run report service of the sperange portal.

One Markdown report per workspace, kept on the portal VM (never on the SPE
instance), written by the participant in a browser page and read by every
portal user. Spec: docs/specs/2026-11-06-run-report-service.md.

Files, under REPORTS_DIR:
    <workspace id>.md     the report (created by playbooks/create.yml, role run_report)
    <workspace id>.json   the sidecar: owner, workspace, instance, created, parameters,
                          template_sha256 (the SHA-256 of the initial content)

Routes (Caddy sends /reports* here):
    GET  /reports/                 the list
    GET  /reports/<id>             the editor page (read-only unless the viewer may write)
    GET  /reports/<id>.md          the Markdown, ETag = sha256 of the file
    PUT  /reports/<id>.md          save; If-Match required; 412 when the file changed
    POST /reports/preview          Markdown in, sanitized HTML fragment out
    GET  /reports/<id>/hits        the canary hit viewer's participant page (spec *Participant
                                    page*); 403 for anyone but the workspace's owner and Coder owners
    GET  /reports/<id>/hits.json   the same hits as JSON, ?after=<id> for only the new ones
    GET  /reports/<id>/hits/events the same hits live, as server-sent events (decision 6); resumes
                                    past Last-Event-ID (else ?after=<id>); ends after 30 minutes,
                                    503 past 200 open streams
    GET  /reports/hits             the admin page (spec *Admin page*): every workspace's row and the
                                    newest 500 hits of all; Coder owners only, 403 for anyone else
    GET  /reports/hits.json        the rows and the newest 2000 hits as JSON
    GET  /reports/hits/events      every workspace's new hits live, ids <workspace id>:<line>; no
                                    resume (the page reloads on reconnect); the same bounds
    GET  /reports/static/<file>    the page's CSS and script
    GET  /reports/healthz          200, no login
    GET  /reports/runs             the runs browser (a page; its data comes from the API below)

The API, JSON unless noted, for the browser page and for scripts (the session token
goes in the coder_session_token cookie or in a Coder-Session-Token header; without
one the answer is 401, never a redirect). Everyone logged in may read all of it:
    GET  /reports/api/reports                                   the live reports (the list above as JSON)
    GET  /reports/api/runs                                      every archived run under RUNS_DIR, newest first
    GET  /reports/api/workspaces/<id>                           one workspace's runs with their chats, and its live report
    GET  /reports/api/runs/<run>                                one run: parameters, report, chats of both frontends
    GET  /reports/api/runs/<run>/report.md                      the archived report, text/markdown
    GET  /reports/api/runs/<run>/chats/<frontend>/<chat>        one chat as turns (role, time, sanitized HTML)
    GET  /reports/api/runs/<run>/chats/<frontend>/<chat>.md     the chat's Markdown as archived
    GET  /reports/api/runs/<run>/chats/<frontend>/<chat>.json   the chat's export as archived
    GET  /reports/api/runs/<run>/agui/agent-runs.jsonl          the agent's run log (AG-UI runs)
    GET  /reports/api/runs/<run>/agui/journals/<session>.jsonl  one AG-UI session journal as stored
<run> is the archive directory's name (<UTC time>_<instance>), <frontend> is openwebui
or agui, <chat> the file stem (01-title). run.yml's participant e-mail is never served;
neither is canaries.json.

Login is Coder's: the browser's coder_session_token cookie is forwarded to
Coder's users/me endpoint and nowhere else. The report's owner (the sidecar's
username) and Coder owners may write; everyone logged in may read. The hits
routes are narrower (decision 10): only the workspace's owner and Coder owners.

Standard library plus python3-markdown and python3-yaml. Environment: CODER_URL
(default http://127.0.0.1:7080), REPORTS_DIR (default /data-share/reports), RUNS_DIR
(default /data-share/runs, the archives written by playbooks/archive.yml), HITS_DIR
(default /data-share/canary-hits, the canary hit viewer's watcher output), LISTEN
(default 127.0.0.1:7090).
"""
from __future__ import annotations

import datetime
import hashlib
import html
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import markdown
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canary_hits import HitsFile  # noqa: E402
from hits_view import (LOUD, UUID_RE, admin_body, empty_text, hit_html, newest_first,  # noqa: E402
                       origin as hit_origin, participant_body, read_all, read_status, scan_ids, status_line,
                       workspace_rows)

PREFIX = "/reports"
API = PREFIX + "/api/"
COOKIE = "coder_session_token"
TOKEN_HEADER = "Coder-Session-Token"
MAX_BYTES = 1_000_000
CACHE_SECONDS = 30
HITS_DIR = "/data-share/canary-hits"
# The event stream, bounded: one thread per open stream, so both its life and their number are bounded.
STREAM_SECONDS = 30 * 60  # then it ends; EventSource reconnects with Last-Event-ID
STREAM_MAX = 200  # open streams per server; past it, 503
STREAM_POLL = 0.5  # seconds between looks at the hits and status files (decision 6: a hit shown within 2 s)
STREAM_READ = 1 << 20  # bytes of the hits file read per look at most (a catch-up takes several)
STREAM_PING = 15  # seconds with nothing sent before a ": ping" comment (keeps proxies from closing it)
STREAM_WRITE_TIMEOUT = 30  # seconds a write may block (a client that stops reading); then the stream ends
STREAM_STATUS_REFRESH = 10  # seconds before an unchanged status is resent, so "watched N s ago" ages live
ADMIN_PAGE_HITS = 500  # hits the admin page renders; the rest are on each workspace's page
ADMIN_JSON_HITS = 2000  # hits the admin hits.json returns; a workspace's full list is its own hits.json
# An archive directory (<UTC time>_<instance>), a chat file stem (01-title), a frontend's chats directory.
RUN_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z_[a-z0-9][a-z0-9._-]*$")
CHAT_RE = re.compile(r"^[0-9]+-[a-z0-9][a-z0-9-]*$")
FRONTEND_DIRS = {"openwebui": "chats", "agui": os.path.join("agui", "chats")}
RUNS_CACHE_SECONDS = 10
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2"}
# Scripts only from here, no inline script; inline styles are allowed because the editor
# (EasyMDE on CodeMirror 5) sets some, and a style cannot reach Coder's cookie.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; "
       "font-src 'self'; frame-ancestors 'none'; form-action 'self'")


# --- Markdown -----------------------------------------------------------------

ALLOWED_TAGS = {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "em", "strong", "code", "pre",
    "blockquote", "a", "table", "thead", "tbody", "tr", "th", "td", "del", "sup", "sub", "img", "details",
    "summary", "dl", "dt", "dd", "span", "div",
}
VOID_TAGS = {"br", "hr", "img"}
ALLOWED_ATTRS = {"a": {"href", "title"}, "img": {"src", "alt", "title"}, "th": {"align"}, "td": {"align"},
                 "ol": {"start"}, "code": {"class"}, "span": {"class"}, "div": {"class"}}
SAFE_SCHEMES = ("http://", "https://", "mailto:", "/", "#")


class Sanitizer(HTMLParser):
    """Keeps an allowlist of tags and attributes; every other tag is escaped and shown as text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self.out.append(html.escape(self.get_starttag_text() or ""))
            return
        kept = []
        for name, value in attrs:
            if name not in ALLOWED_ATTRS.get(tag, set()):
                continue
            value = value or ""
            if name in ("href", "src") and not value.strip().lower().startswith(SAFE_SCHEMES):
                continue
            kept.append(f' {name}="{html.escape(value, quote=True)}"')
        self.out.append(f"<{tag}{''.join(kept)}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.out.append(f"</{tag}>")
        elif tag not in ALLOWED_TAGS:
            self.out.append(html.escape(f"</{tag}>"))

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass


def render_markdown(text: str) -> str:
    """Markdown to an HTML fragment that cannot carry script: rendered, then reduced to the allowlist."""
    rendered = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    s = Sanitizer()
    s.feed(rendered)
    s.close()
    return "".join(s.out)


# --- storage ------------------------------------------------------------------

class Conflict(Exception):
    pass


class Store:
    def __init__(self, root: str):
        self.root = root
        self.lock = threading.Lock()

    def _md(self, wid):
        return os.path.join(self.root, wid + ".md")

    def _json(self, wid):
        return os.path.join(self.root, wid + ".json")

    def meta(self, wid: str) -> dict | None:
        try:
            with open(self._json(wid), encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            return None
        return m if isinstance(m, dict) else None

    def read(self, wid: str) -> tuple[bytes, str] | None:
        try:
            with open(self._md(wid), "rb") as f:
                data = f.read()
        except OSError:
            return None
        return data, etag_of(data)

    def last_saved(self, wid: str) -> str:
        try:
            return iso(os.stat(self._md(wid)).st_mtime)
        except OSError:
            return ""

    def write(self, wid: str, data: bytes, if_match: str) -> str:
        with self.lock:
            current = self.read(wid)
            if current is None:
                raise FileNotFoundError(wid)
            if current[1] != if_match:
                raise Conflict(current[1])
            tmp = self._md(wid) + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, self._md(wid))
            # "last saved" is this host's clock, not the file server's (NFS would use its own).
            now = time.time()
            os.utime(self._md(wid), (now, now))
        return etag_of(data)

    def listing(self) -> list[dict]:
        rows = []
        try:
            names = os.listdir(self.root)
        except OSError:
            names = []
        for name in names:
            wid = name[:-5]
            if not name.endswith(".json") or not UUID_RE.match(wid):
                continue
            m = self.meta(wid)
            if m is None or not os.path.isfile(self._md(wid)):
                continue
            rows.append({**m, "workspace_id": wid, "last_saved": self.last_saved(wid)})
        rows.sort(key=lambda r: r.get("last_saved", ""), reverse=True)
        return rows


# --- the archived runs ---------------------------------------------------------
# playbooks/archive.yml writes one directory per stopped workspace under RUNS_DIR:
# run.yml (parameters), report.md/.json (the report as it was), chats/<nn>-<title>.json|.md
# (Open WebUI), agui/chats/... (AG-UI, rendered the same way), agui/agent-runs.jsonl and
# agui/agui-journals/<session>.jsonl (raw). Read-only here; a listing is cached briefly.

TURN_RE = re.compile(r"^## (?P<role>[^(·\n]+?)(?: \((?P<model>[^)]*)\))?(?: · (?P<rest>.*))?$")
TURN_ROLES = ("user", "assistant", "system", "tool")
# write_run.py's own '##' sections in an AG-UI chat; any other '##' line is the model's text.
TURN_SECTIONS = ("Compacted", "Other branches", "sent by the client, not used")
HIDDEN_RUN_KEYS = ("participant_email", "owner_email")


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def public(d: dict) -> dict:
    """A run's or report's metadata without the fields that are not for other participants."""
    return {k: v for k, v in d.items() if k not in HIDDEN_RUN_KEYS}


def split_turns(md: str, render: bool = True) -> tuple[dict, list[dict]]:
    """A chat as write_run.py renders it: a title, '- Key: value' facts, then one '## role · time'
    heading per turn (Open WebUI adds the model in parentheses; AG-UI has a few other '##' sections,
    'Compacted', 'Other branches', which become turns of their own kind). A '##' line the model wrote
    in its answer is not a turn: it stays in the body, like everything inside a code fence."""
    facts: dict[str, str] = {}
    turns: list[dict] = []
    current: dict | None = None
    body: list[str] = []
    in_fence = False

    def close():
        if current is not None:
            text = "\n".join(body).strip("\n")
            current["markdown"] = text
            if render:
                current["html"] = render_markdown(text)
            turns.append(current)

    for line in md.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        m = TURN_RE.match(line) if not in_fence and line.startswith("## ") else None
        if m and (m.group("role").strip().lower() in TURN_ROLES and m.group("rest") is not None
                  or m.group("role").strip() in TURN_SECTIONS):
            close()
            role = m.group("role").strip()
            current = {"role": role.lower() if role.lower() in TURN_ROLES else "section",
                       "label": role, "model": m.group("model") or "", "at": m.group("rest") or ""}
            body = []
            continue
        if current is None:
            if stripped.startswith("- ") and ": " in stripped:
                k, _, v = stripped[2:].partition(": ")
                facts[k.strip()] = v.strip()
            continue
        body.append(line)
    close()
    return facts, turns


# --- the threat score -----------------------------------------------------------
# How much a user turn resembles known adversarial prompts: the same model file and arithmetic as
# the agent's POST /threat-score (platform/agui/pydantic-ai-agent/src/spe_agent/threat.py), here for
# the archived chats. The turn is embedded by an OpenAI-compatible endpoint (THREAT_EMBEDDINGS_URL,
# THREAT_EMBEDDINGS_KEY) and scored by threat_model.json next to this file: logistic regressions on
# the embedding, one general head and one per category. Without the endpoint, or when it fails, the
# chats are served without scores. Scores are kept in memory only.

THREAT_EMBED_CHARS = 6000   # what is embedded, as in training
THREAT_BATCH = 32
THREAT_CACHE = 4096


def threat_display(p: float, elevated: float, high: float) -> int:
    """A probability on the head's own scale: 50 is its `elevated` threshold (5% of benign in-domain
    prompts score above it), 75 its `high` threshold (1%)."""
    if p < elevated:
        value = 50 * p / elevated if elevated > 0 else 50.0
    elif p < high:
        value = 50 + 25 * (p - elevated) / (high - elevated)
    else:
        value = 75 + 25 * (p - high) / (1 - high) if high < 1 else 100.0
    return max(0, min(100, round(value)))


def threat_level(score: int) -> str:
    return "high" if score >= 75 else "elevated" if score >= 50 else "low"


class ThreatScorer:
    def __init__(self, model_path: str, base_url: str, api_key: str, embedding_model: str, post=None, timeout: float = 15.0):
        with open(model_path, encoding="utf-8") as f:
            data = json.load(f)
        self.heads = data["heads"]
        self.dimensions = data["dimensions"]
        self.info = {"version": data["version"], "trained": data["trained"], "embedding_model": data["embedding_model"]}
        if not self.heads or self.heads[0]["id"] != "general" or any(len(h["weights"]) != self.dimensions for h in self.heads):
            raise ValueError(f"{model_path}: not a threat model")
        self.url = base_url.rstrip("/") + "/embeddings"
        self.api_key = api_key
        self.embedding_model = embedding_model
        self.timeout = timeout
        self._post = post or self._http_post
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _http_post(self, body: dict) -> dict:
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def score(self, embedding: list[float]) -> dict:
        if len(embedding) != self.dimensions:
            raise ValueError(f"the embedding has {len(embedding)} dimensions, the model needs {self.dimensions}")
        norm = math.sqrt(sum(v * v for v in embedding)) or 1.0
        x = [v / norm for v in embedding]
        scored = []
        for head in self.heads:
            z = sum(w * v for w, v in zip(head["weights"], x)) + head["bias"]
            p = 1 / (1 + math.exp(-z)) if z > -700 else 0.0
            value = threat_display(p, head["elevated"], head["high"])
            scored.append({"id": head["id"], "label": head["label"], "score": value, "level": threat_level(value),
                           "examples": head["examples"], "auc": head["auc"]})
        general, categories = scored[0], sorted(scored[1:], key=lambda c: -c["score"])
        return {"score": general["score"], "level": general["level"], "categories": categories}

    def scores(self, texts: list[str]) -> list[dict | None]:
        """One score per text, None where there is none (an empty text, or the endpoint failed)."""
        keys = [t.strip()[:THREAT_EMBED_CHARS] for t in texts]
        with self._lock:
            todo = [k for k in dict.fromkeys(keys) if k and k not in self._cache]
        try:
            for i in range(0, len(todo), THREAT_BATCH):
                batch = todo[i:i + THREAT_BATCH]
                data = self._post({"model": self.embedding_model, "input": batch})["data"]
                rows = sorted(data, key=lambda e: e["index"])
                if len(rows) != len(batch):
                    raise ValueError(f"{len(rows)} embeddings for {len(batch)} texts")
                fresh = {k: self.score(e["embedding"]) for k, e in zip(batch, rows)}
                with self._lock:
                    while len(self._cache) + len(fresh) > THREAT_CACHE:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache.update(fresh)
        except Exception as e:  # the chats are served without scores; the reason only, never the key
            print(f"sperange-report: threat score unavailable: {type(e).__name__}: {str(e)[:200]}", flush=True)
        with self._lock:
            return [self._cache.get(k) for k in keys]


class Runs:
    def __init__(self, root: str, threat: ThreatScorer | None = None):
        self.root = root
        self.threat = threat
        self.lock = threading.Lock()
        self._listing: tuple[float, list[dict]] | None = None

    # ---- paths (every component validated by the caller's regexes; nothing else joins a path)
    def dir(self, rid: str) -> str:
        return os.path.join(self.root, rid)

    def chat_path(self, rid: str, frontend: str, chat: str, ext: str) -> str:
        return os.path.join(self.dir(rid), FRONTEND_DIRS[frontend], chat + ext)

    def exists(self, rid: str) -> bool:
        return bool(RUN_RE.match(rid)) and (os.path.isfile(os.path.join(self.dir(rid), "run.yml"))
                                             or os.path.isfile(os.path.join(self.dir(rid), "report.json")))

    # ---- metadata
    def params(self, rid: str) -> dict:
        try:
            with open(os.path.join(self.dir(rid), "run.yml"), encoding="utf-8") as f:
                y = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            y = None
        if not isinstance(y, dict):
            y = {}
            side = _read_json(os.path.join(self.dir(rid), "report.json"))
            if isinstance(side, dict):  # an older archive without run.yml: what the sidecar knows
                y = {"instance": side.get("instance"), "participant": side.get("owner"),
                     "coder_workspace": side.get("workspace"), **(side.get("parameters") or {})}
        return public(y)

    def report(self, rid: str) -> dict | None:
        md = _read_text(os.path.join(self.dir(rid), "report.md"))
        if md is None:
            return None
        side = _read_json(os.path.join(self.dir(rid), "report.json"))
        side = side if isinstance(side, dict) else {}
        template = side.get("template_sha256")
        filled = hashlib.sha256(md.encode("utf-8")).hexdigest() != template if template else None
        return {"markdown": md, "filled": filled, "workspace_id": side.get("workspace_id"),
                "created": side.get("created")}

    def chats(self, rid: str) -> list[dict]:
        rows = []
        for frontend, sub in FRONTEND_DIRS.items():
            d = os.path.join(self.dir(rid), sub)
            try:
                names = sorted(os.listdir(d))
            except OSError:
                continue
            for name in names:
                stem, ext = os.path.splitext(name)
                if ext != ".json" or not CHAT_RE.match(stem) or not os.path.isfile(os.path.join(d, stem + ".md")):
                    continue
                c = _read_json(os.path.join(d, name))
                c = c if isinstance(c, dict) else {}
                chat = c.get("chat") if isinstance(c.get("chat"), dict) else {}
                messages = chat.get("messages") if isinstance(chat.get("messages"), list) else []
                history = (chat.get("history") or {}).get("messages") if isinstance(chat.get("history"), dict) else None
                rows.append({
                    "frontend": frontend, "id": stem,
                    "title": str(c.get("title") or chat.get("title") or stem),
                    "created": when(c.get("created_at")), "updated": when(c.get("updated_at")),
                    "messages": len(history) if isinstance(history, dict) and history else len(messages),
                    "tags": [str(t.get("name") if isinstance(t, dict) else t) for t in (chat.get("tags") or [])
                             if t] if isinstance(chat.get("tags"), list) else [],
                    "archived": bool(c.get("archived")),
                })
        return rows

    def files(self, rid: str) -> dict:
        agui = os.path.join(self.dir(rid), "agui")
        journals = []
        try:
            journals = sorted(n[:-6] for n in os.listdir(os.path.join(agui, "agui-journals"))
                              if n.endswith(".jsonl") and UUID_RE.match(n[:-6]))
        except OSError:
            pass
        return {"agent_runs": os.path.isfile(os.path.join(agui, "agent-runs.jsonl")), "journals": journals}

    def summary(self, rid: str) -> dict:
        params = self.params(rid)
        chats = self.chats(rid)
        report = self.report(rid)
        counts = {f: sum(1 for c in chats if c["frontend"] == f) for f in FRONTEND_DIRS}
        return {
            "id": rid,
            "archived_at": str(params.get("archived_at") or rid.split("_", 1)[0]),
            "instance": str(params.get("instance") or rid.split("_", 1)[-1]),
            "participant": str(params.get("participant") or ""),
            "workspace": str(params.get("coder_workspace") or ""),
            "model": str(params.get("model") or ""),
            "flavor": str(params.get("flavor") or ""),
            "frontends": [str(f) for f in params.get("frontends") or []],
            "workflows": [str(w) for w in params.get("workflows") or []],
            "samples": [str(x) for x in params.get("samples") or []],
            "tiers": [str(x) for x in params.get("tiers") or []],
            "seed": params.get("seed"),
            "chats": counts,
            "report": None if report is None else {"filled": report["filled"], "workspace_id": report["workspace_id"]},
        }

    def listing(self) -> list[dict]:
        now = time.monotonic()
        with self.lock:
            if self._listing and self._listing[0] > now:
                return self._listing[1]
        try:
            names = os.listdir(self.root)
        except OSError:
            names = []
        rows = [self.summary(rid) for rid in sorted(names, reverse=True) if self.exists(rid)]
        with self.lock:
            self._listing = (now + RUNS_CACHE_SECONDS, rows)
        return rows

    def for_workspace(self, wid: str, instance: str | None) -> list[dict]:
        """The runs of one workspace: those whose archived report sidecar names it, or (archives
        without a sidecar) whose instance is the one the workspace's live sidecar names."""
        rows = []
        for s in self.listing():
            report = s.get("report") or {}
            if report.get("workspace_id") == wid or (instance and s["instance"] == instance and not report.get("workspace_id")):
                rows.append({**s, "chat_list": self.chats(s["id"])})
        return rows

    def detail(self, rid: str) -> dict:
        d = self.summary(rid)
        d["parameters"] = self.params(rid)
        d["chat_list"] = self.with_threat(rid, self.chats(rid))
        report = self.report(rid)
        if report is not None:
            d["report"] = {**report, "html": render_markdown(report["markdown"])}
        d["files"] = self.files(rid)
        return d

    def with_threat(self, rid: str, chats: list[dict]) -> list[dict]:
        """Each chat with the highest threat score among its user turns (one request for the whole run)."""
        if self.threat is None:
            return chats
        texts: list[str] = []
        spans = []
        for c in chats:
            md = _read_text(self.chat_path(rid, c["frontend"], c["id"], ".md")) or ""
            mine = [t["markdown"] for t in split_turns(md, render=False)[1] if t["role"] == "user"]
            spans.append((len(texts), len(texts) + len(mine)))
            texts += mine
        scores = self.threat.scores(texts)
        out = []
        for c, (a, b) in zip(chats, spans):
            top = max((s for s in scores[a:b] if s), key=lambda s: s["score"], default=None)
            out.append({**c, "threat": {"score": top["score"], "level": top["level"]}} if top else c)
        return out

    def chat(self, rid: str, frontend: str, chat: str) -> dict | None:
        md = _read_text(self.chat_path(rid, frontend, chat, ".md"))
        if md is None:
            return None
        facts, turns = split_turns(md)
        if self.threat is not None:
            users = [t for t in turns if t["role"] == "user"]
            for t, score in zip(users, self.threat.scores([t["markdown"] for t in users])):
                if score:
                    t["threat"] = score
        meta = next((c for c in self.chats(rid) if c["frontend"] == frontend and c["id"] == chat), None)
        title = md.split("\n", 1)[0].lstrip("# ").strip() if md.startswith("# ") else chat
        return {"run": rid, "frontend": frontend, "id": chat, "title": (meta or {}).get("title") or title,
                "meta": meta, "facts": facts, "turns": turns,
                "threat_model": self.threat.info if self.threat is not None else None,
                "links": {"markdown": f"{API}runs/{rid}/chats/{frontend}/{chat}.md",
                          "json": f"{API}runs/{rid}/chats/{frontend}/{chat}.json"}}

    def raw(self, rid: str, relpath: str) -> bytes | None:
        """A file of the archive by a path the caller has already validated component by component."""
        try:
            with open(os.path.join(self.dir(rid), relpath), "rb") as f:
                return f.read()
        except OSError:
            return None


def when(t) -> str:
    """Epoch seconds or milliseconds (Open WebUI and AG-UI exports) to '2026-11-03 10:00 UTC'."""
    try:
        s = float(t)
    except (TypeError, ValueError):
        return str(t or "")
    if s > 1e11:
        s /= 1000
    try:
        return iso(s)
    except (OverflowError, OSError, ValueError):
        return str(t)


def etag_of(data: bytes) -> str:
    return '"' + hashlib.sha256(data).hexdigest() + '"'


def iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# --- Coder --------------------------------------------------------------------

class Coder:
    """Coder's API as seen with the viewer's session token. Answers to users/me are cached briefly."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.cache: dict[str, tuple[float, dict | None]] = {}
        self.lock = threading.Lock()

    def _get(self, path: str, token: str):
        req = urllib.request.Request(self.url + path, headers={"Coder-Session-Token": token, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                return None
            raise

    def me(self, token: str) -> dict | None:
        now = time.monotonic()
        with self.lock:
            hit = self.cache.get(token)
            if hit and hit[0] > now:
                return hit[1]
        user = self._get("/api/v2/users/me", token)
        if user is not None and not isinstance(user, dict):
            user = None
        with self.lock:
            self.cache[token] = (now + CACHE_SECONDS, user)
            if len(self.cache) > 1000:
                self.cache = {k: v for k, v in self.cache.items() if v[0] > now}
        return user

    def workspace_state(self, token: str, wid: str) -> str | None:
        try:
            ws = self._get(f"/api/v2/workspaces/{wid}", token)
        except (urllib.error.URLError, OSError, ValueError):
            return None
        if not isinstance(ws, dict):
            return None
        build = ws.get("latest_build") or {}
        return str(build.get("status") or "") or None


def is_admin(user: dict) -> bool:
    return any(isinstance(r, dict) and r.get("name") == "owner" for r in user.get("roles") or [])


# --- pages --------------------------------------------------------------------
# The look follows the landing page (platform/site/static/site.css): the same tokens,
# top bar and cards. The editor is EasyMDE (vendored in static/, with Font Awesome 4
# for its toolbar); readers get the rendered report instead of an editor.

def page(title: str, body: str, user: dict | None, editor: bool = False, styles: tuple[str, ...] = (),
         scripts: tuple[str, ...] = ("report.js",)) -> bytes:
    """`scripts` and `styles` are file names under `static/` (the runs browser's `runs.js`, the hits
    page's `hits.js` and `report.js`), linked absolute like the page's own (`{PREFIX}/static/<name>`);
    always with a `src`/`href`, never inline (the CSP forbids inline script)."""
    who = html.escape(user.get("username", "")) if user else ""
    extra = (f"<link rel=\"stylesheet\" href=\"{PREFIX}/static/font-awesome.min.css\">"
             f"<link rel=\"stylesheet\" href=\"{PREFIX}/static/easymde.min.css\">" if editor else "")
    extra += "".join(f"<link rel=\"stylesheet\" href=\"{PREFIX}/static/{html.escape(name)}\">" for name in styles)
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title>{extra}"
        f"<link rel=\"stylesheet\" href=\"{PREFIX}/static/report.css\"></head>"
        "<body><div class=\"wrap\"><header class=\"top\"><a class=\"brand\" href=\"/\">SPE Range</a>"
        f"<nav><a href=\"/workspaces\">Portal</a><a href=\"/threats/\">Catalog</a>"
        f"<a href=\"{PREFIX}/runs\">Runs</a><a href=\"{PREFIX}/\">Reports</a>"
        f"<span class=\"who\">{who}</span></nav></header>{body}</div>"
        + (f"<script src=\"{PREFIX}/static/easymde.min.js\"></script>" if editor else "")
        + "".join(f"<script src=\"{PREFIX}/static/{html.escape(name)}\"></script>" for name in scripts)
        + "</body></html>"
    ).encode()


def runs_page(user: dict) -> bytes:
    """The runs browser: a shell the script fills from the API (list, one run, one chat; the view is in
    the URL's hash so every state has a link). Without script it says where the data is."""
    body = (f"<main class=\"runs\" id=\"runs\" data-api=\"{API}\" data-reports=\"{PREFIX}/\">"
            "<h1>Runs</h1><p class=\"lead\">Every archived run of the range and the live reports of the "
            "workspaces that exist now. Everyone logged in can read them.</p>"
            f"<noscript><p>This page needs JavaScript. The same data is at <a href=\"{API}runs\">{API}runs</a> "
            f"and <a href=\"{API}reports\">{API}reports</a> as JSON.</p></noscript>"
            "<div id=\"view\" class=\"view\" aria-live=\"polite\"><p class=\"muted\">Loading…</p></div></main>")
    return page("Runs", body, user, styles=("runs.css",), scripts=("runs.js",))


def list_page(rows: list[dict], user: dict) -> bytes:
    trs = []
    for r in rows:
        wid = r["workspace_id"]
        trs.append(
            f"<tr><td><a href=\"{PREFIX}/{wid}\">{html.escape(str(r.get('workspace') or wid))}</a></td>"
            f"<td>{html.escape(str(r.get('owner') or ''))}</td>"
            f"<td><code>{html.escape(str(r.get('instance') or ''))}</code></td>"
            f"<td>{html.escape(str(r.get('created') or ''))}</td>"
            f"<td>{html.escape(r.get('last_saved') or '')}</td></tr>"
        )
    table = ("<table><thead><tr><th>Workspace</th><th>Owner</th><th>Instance</th><th>Created</th>"
             "<th>Last saved</th></tr></thead><tbody>" + "".join(trs) + "</tbody></table>"
             if trs else "<p class=\"muted\">No report yet. A report is created with each workspace.</p>")
    admin_link = (f"<p class=\"admin-link\"><a href=\"{PREFIX}/hits\">Canary hits</a></p>"
                  if is_admin(user) else "")
    body = f"<main class=\"list\"><h1>Run reports</h1>{admin_link}<section class=\"card\">{table}</section></main>"
    return page("Run reports", body, user)


def facts_html(wid: str, meta: dict, state: str | None) -> str:
    facts = [
        ("Workspace", str(meta.get("workspace") or wid)),
        ("Owner", str(meta.get("owner") or "")),
        ("Instance", str(meta.get("instance") or "")),
        ("Created", str(meta.get("created") or "")),
    ]
    if state:
        facts.append(("Workspace", f"{meta.get('workspace') or wid} ({state})"))
        facts.pop(0)
    return "".join(f"<div class=\"fact\"><span class=\"k\">{html.escape(k)}</span>"
                   f"<span class=\"v\">{html.escape(v)}</span></div>" for k, v in facts if v)


def editor_page(wid: str, meta: dict, user: dict, can_edit: bool, state: str | None, last_saved: str,
                content: bytes) -> bytes:
    head = (f"<header class=\"report-head card\"><div class=\"title\"><h1>Run report</h1>"
            f"<div class=\"facts\">{facts_html(wid, meta, state)}</div></div>")
    if can_edit:
        head += ("<div class=\"bar\"><span class=\"hint\">Saved as you type, readable by every portal user.</span>"
                 f"<span id=\"status\" data-last-saved=\"{html.escape(last_saved)}\"></span>"
                 "<button id=\"save\" type=\"button\">Save</button></div></header>")
        body = (f"<main class=\"editor\" data-id=\"{wid}\" data-can-edit=\"1\">{head}"
                "<section class=\"card editor-card\"><textarea id=\"source\"></textarea></section></main>")
    else:
        head += ("<div class=\"bar\"><span class=\"hint\">Read-only: only the owner and portal admins can edit."
                 f"{' Last saved ' + html.escape(last_saved) + '.' if last_saved else ''}</span>"
                 f"<a class=\"raw\" href=\"{PREFIX}/{wid}.md\">Markdown</a></div></header>")
        body = (f"<main class=\"editor\" data-id=\"{wid}\" data-can-edit=\"0\">{head}"
                f"<article class=\"card reading\">{render_markdown(content.decode('utf-8', 'replace'))}</article></main>")
    return page(f"Run report: {meta.get('workspace') or wid}", body, user, editor=can_edit)


def message_page(title: str, text: str, user: dict | None = None) -> bytes:
    return page(title, f"<main class=\"list\"><h1>{html.escape(title)}</h1><p>{html.escape(text)}</p></main>", user)


# --- the server ---------------------------------------------------------------

def log_stream_error(wid: str, error: OSError, what: str) -> None:
    """One log line for a hits file a stream cannot read: the workspace id and the error's class
    only (no path, no content)."""
    sys.stdout.write(f"hits stream {wid}: {type(error).__name__}, {what}\n")
    sys.stdout.flush()


class Tail:
    """One hits file followed by an event stream, read in bounded looks: `poll` returns the complete
    lines past `start` (as line number, raw bytes) added since the last look. Line numbers are the
    hits' ids. A start past the file's end is clamped to it (nothing replayed); `END` starts at
    whatever end the file has when first read."""

    END = sys.maxsize

    def __init__(self, path: str, start: int):
        self.path, self.start = path, start
        self.lines, self.offset = 0, 0  # complete lines passed so far, and the byte offset after them
        self.inode = None  # the file's, once seen: a file replaced or cut ends the stream
        self.caught_up = False  # `start` reached, or clamped to the file's end once the end was read
        self.in_long_line = False  # inside a line longer than one read, skipped (it still counts as a line)

    def poll(self, read_size: int) -> list[tuple[int, bytes]] | None:
        """The new lines, or None when the stream should end: the file was replaced, cut or removed
        after it was read (a reconnect is clamped to the new end, so it cannot loop). A file that
        cannot be read at all raises its OSError: the caller decides what that ends."""
        data = b""
        try:
            with open(self.path, "rb") as f:
                st = os.fstat(f.fileno())
                if self.inode is not None and (st.st_ino != self.inode or st.st_size < self.offset):
                    return None  # replaced or cut: the browser reconnects and is clamped afresh
                self.inode = st.st_ino
                f.seek(self.offset)
                data = f.read(read_size)
        except FileNotFoundError:
            if self.inode is not None:
                return None  # removed after it was read
            self.caught_up = True  # no hits yet: nothing to skip, the first hit is id 1
        at_end = len(data) < read_size
        if self.in_long_line:
            nl = data.find(b"\n")
            self.offset += len(data) if nl < 0 else nl + 1
            if nl >= 0:
                self.lines, self.in_long_line = self.lines + 1, False
            data = b"" if nl < 0 else data[nl + 1:]
        # Only complete lines: a line still being written is read again on the next look.
        complete = data[:data.rfind(b"\n") + 1]
        if not complete and len(data) >= read_size:  # a whole read and no line end: too long
            self.offset, self.in_long_line = self.offset + len(data), True
        out = []
        for raw in complete.split(b"\n")[:-1]:
            self.lines += 1
            self.offset += len(raw) + 1
            if self.lines <= self.start and not self.caught_up:
                continue
            out.append((self.lines, raw))
        if at_end:
            self.caught_up = True  # a start past the end is clamped to it: nothing replayed, no error
        return out


class Handler(BaseHTTPRequestHandler):
    server_version = "sperange-report/1"
    store: Store
    coder: Coder
    hits_dir: str | None = None
    runs: Runs

    # ---- helpers
    def send(self, status: int, body: bytes = b"", ctype: str = "text/html; charset=utf-8", headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status: int, obj: dict, headers: dict | None = None):
        self.send(status, json.dumps(obj).encode(), "application/json", headers)

    def token(self) -> str:
        header = self.headers.get(TOKEN_HEADER, "").strip()
        if header:
            return header
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except Exception:  # a malformed cookie header is no session
            return ""
        return c[COOKIE].value if COOKIE in c else ""

    def user(self) -> dict | None:
        """The viewer, or None. Raises on a Coder outage (answered as 502 by the caller)."""
        tok = self.token()
        return self.coder.me(tok) if tok else None

    def same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return urllib.parse.urlsplit(origin).netloc == host

    def route(self) -> tuple[str, str]:
        path = urllib.parse.urlsplit(self.path).path
        if path == PREFIX:
            path = PREFIX + "/"
        if not path.startswith(PREFIX + "/"):
            return "", ""
        return path, path[len(PREFIX) + 1:]

    def log_message(self, fmt, *args):  # no cookie, no query string
        sys.stdout.write("%s %s %s\n" % (self.address_string(), self.command, urllib.parse.urlsplit(self.path).path))
        sys.stdout.flush()

    def login_redirect(self, path: str):
        self.send(HTTPStatus.FOUND, b"", headers={"Location": "/login?redirect=" + urllib.parse.quote(path, safe="")})

    def can_edit(self, meta: dict, user: dict) -> bool:
        return user.get("username") == meta.get("owner") or is_admin(user)

    def can_see_hits(self, meta: dict | None, user: dict) -> bool:
        """Decision 10: the workspace's owner and Coder owners; a workspace with no report sidecar
        (`meta` None) is visible to admins only. `meta.get`: a sidecar with no `owner` means only
        admins, not a KeyError (500)."""
        return is_admin(user) or (meta is not None and user["username"] == meta.get("owner"))

    # ---- the canary hit viewer's pages (spec *Participant page*)

    def _hits_path(self, wid: str) -> str | None:
        return os.path.join(self.hits_dir, wid + ".jsonl") if self.hits_dir else None

    def _status_path(self, wid: str) -> str | None:
        return os.path.join(self.hits_dir, wid + ".status.json") if self.hits_dir else None

    def read_hits(self, wid: str, after: int = 0) -> list[dict]:
        path = self._hits_path(wid)
        return HitsFile(path).read(after=after) if path else []

    def read_status(self, wid: str) -> dict | None:
        """The watcher's status file (`<id>.status.json`), or None: no `hits_dir`, no file, or one that is
        not valid JSON or not an object (never raises on it: untrusted only in the sense that the
        watcher could be mid-write, never the participant's)."""
        path = self._status_path(wid)
        return read_status(path) if path else None

    def hits_page(self, wid: str, user: dict) -> None:
        if not UUID_RE.match(wid):
            return self.send(HTTPStatus.NOT_FOUND, message_page("Not found", "No such workspace.", user))
        meta = self.store.meta(wid)
        if not self.can_see_hits(meta, user):
            return self.send(HTTPStatus.FORBIDDEN, message_page(
                "Forbidden", "Only the workspace's owner and Coder owners can see its canary hits.", user))
        hits = self.read_hits(wid)
        status = self.read_status(wid)
        label = (meta or {}).get("workspace") or wid
        body_meta = meta if meta is not None else {"workspace": wid}
        body_status = status if status is not None else {}  # {}: "not watched yet", never "archived run"
        last = hits[-1]["id"] if hits else 0
        content = (f'<section id="hits" data-wid="{html.escape(wid)}" data-last="{last}">'
                   f'{participant_body(body_meta, hits, body_status)}</section>')
        return self.send(HTTPStatus.OK, page(f"Canary hits · {label}", content, user,
                                             scripts=("hits.js", "report.js"), styles=("hits.css",)))

    def hits_json(self, wid: str, user: dict) -> None:
        if not UUID_RE.match(wid):
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        meta = self.store.meta(wid)
        if not self.can_see_hits(meta, user):
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        after = 0
        if "after" in query:
            try:
                after = int(query["after"][-1])
            except ValueError:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "after must be an integer"})
        return self.send_json(HTTPStatus.OK, {"workspace": wid, "status": self.read_status(wid),
                                              "hits": self.read_hits(wid, after)})

    # ---- the admin page (spec *Admin page*; decision 7): Coder owners only

    def _admin_data(self) -> tuple[list[dict], list[dict]]:
        """The workspace rows and every hit of every workspace, newest first."""
        if not self.hits_dir:
            return [], []
        by_ws = read_all(self.hits_dir)
        metas = {wid: self.store.meta(wid) for wid in by_ws}
        rows = workspace_rows(self.hits_dir, metas, by_ws)
        return rows, newest_first([h for hits in by_ws.values() for h in hits])

    def admin_page(self, user: dict) -> None:
        if not is_admin(user):
            return self.send(HTTPStatus.FORBIDDEN, message_page(
                "Forbidden", "Only Coder owners can see every workspace's canary hits.", user))
        rows, hits = self._admin_data()
        token = self.token()
        # One lookup per row with the viewer's token; a failure leaves that row's state blank.
        states = {r["workspace"]: self.coder.workspace_state(token, r["workspace"]) for r in rows}
        shown = hits[:ADMIN_PAGE_HITS]
        content = (f'<section id="admin-hits-page">'
                   f'{admin_body(rows, shown, states, more=len(hits) - len(shown))}</section>')
        return self.send(HTTPStatus.OK, page("Canary hits · all workspaces", content, user,
                                             scripts=("hits-admin.js", "report.js"), styles=("hits.css",)))

    def admin_json(self, user: dict) -> None:
        if not is_admin(user):
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
        rows, hits = self._admin_data()
        return self.send_json(HTTPStatus.OK, {"workspaces": rows, "hits": hits[:ADMIN_JSON_HITS]})

    def admin_events(self, user: dict) -> None:
        if not is_admin(user):
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
        if not self.hits_dir:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "no hits directory"})
        self._event_stream(self._stream_all)

    def hits_events(self, wid: str, user: dict) -> None:
        """The event stream (spec *Participant page*; decision 6; bounded in life and number): resumes past
        Last-Event-ID (else ?after=), and sends a status event whenever the watcher's status changes."""
        if not UUID_RE.match(wid):
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        if not self.can_see_hits(self.store.meta(wid), user):
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
        self._event_stream(lambda: self._stream(wid, self._stream_start()))

    def _event_stream(self, run) -> None:
        """Opens an event stream and runs `run` to write it (a bounded number open at once).
        Not sent through `send`: no Content-Length, and each event is written as it is found. Its
        timings and cap are the server's attributes (`make_server`), so tests can shorten them."""
        srv = self.server
        with srv.streams_lock:
            if srv.streams >= srv.stream_max:
                full = True
            else:
                full, srv.streams = False, srv.streams + 1
        if full:
            return self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "too many open streams"},
                                  {"Retry-After": "60"})
        try:
            self.close_connection = True
            # A client that stops reading would otherwise block wfile.write forever, past the 30-minute
            # bound and holding its stream slot; the timeout makes the TimeoutError catch below real.
            self.connection.settimeout(srv.stream_write_timeout)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.flush()
            if self.command != "HEAD":
                run()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            pass  # the viewer went away, or stopped reading
        finally:
            with srv.streams_lock:
                srv.streams -= 1

    def _stream_start(self) -> int:
        """Where the stream resumes: Last-Event-ID when it is an integer, else ?after=, else 0."""
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        for value in (self.headers.get("Last-Event-ID"), (query.get("after") or [None])[-1]):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0

    def _pump(self, look) -> None:
        """The stream's loop: every stream_poll seconds, `look()` returns the events to send (a list of
        strings) or None to end the stream; a ping when nothing was sent for stream_ping seconds; ends
        after stream_seconds."""
        srv = self.server
        ends = time.monotonic() + srv.stream_seconds
        last_sent = time.monotonic()
        while time.monotonic() < ends:
            out = look()
            if out is None:
                return
            if not out and time.monotonic() - last_sent >= srv.stream_ping:
                out.append(": ping\n\n")
            if out:
                self.wfile.write("".join(out).encode())
                self.wfile.flush()
                last_sent = time.monotonic()
            time.sleep(srv.stream_poll)

    def _stream(self, wid: str, start: int) -> None:
        srv = self.server
        tail = Tail(self._hits_path(wid), start) if self.hits_dir else None
        status_path = self._status_path(wid)
        status_seen = None  # the status file's (mtime, inode) last sent; None: never sent
        status_sent = time.monotonic()  # when a status event was last sent; also refreshes it

        def look():
            nonlocal status_seen, status_sent
            out = []
            if tail:
                try:
                    lines = tail.poll(srv.stream_read)
                except OSError as e:
                    log_stream_error(wid, e, "ended")
                    return None
                if lines is None:
                    return None
                out.extend(e for e in (self._hit_event(n, raw) for n, raw in lines) if e)
            if status_path:
                try:
                    st = os.stat(status_path)
                    stamp = (st.st_mtime_ns, st.st_ino)
                except OSError:
                    stamp = None
                now_mono = time.monotonic()
                # Resent on change, or unchanged past stream_status_refresh: "watched N s ago"
                # would otherwise freeze once the watcher stops touching the status file.
                if stamp is not None and (stamp != status_seen or now_mono - status_sent >= srv.stream_status_refresh):
                    status_seen, status_sent = stamp, now_mono
                    status = self.read_status(wid) or {}
                    line = status_line(status, time.time())
                    out.append("event: status\ndata: " + json.dumps({"line": line, "empty": empty_text(status)}) + "\n\n")
            return out
        self._pump(look)

    def _stream_all(self) -> None:
        """The admin stream (spec *Admin page*): every workspace's hits file, rescanned on each look so
        a new workspace's file joins. A file there when the stream opened is followed from its end (no
        resume: the page reloads on reconnect); one that appears later, from its first line. Event ids
        are `<workspace id>:<line number>`; no status events (the page's status column is rendered).
        A file that cannot be read is dropped for the rest of this stream (logged once) and the others
        go on: ending the stream would only make the page reload into the same unreadable file."""
        srv = self.server
        tails: dict[str, Tail] = {}
        dropped: set[str] = set()
        first = True

        def look():
            nonlocal first
            out = []
            wids = scan_ids(self.hits_dir)
            if wids is None:
                return []  # the directory could not be listed: try again, still the first scan
            for wid in wids:
                if wid in dropped:
                    continue
                if wid not in tails:
                    tails[wid] = Tail(self._hits_path(wid), start=Tail.END if first else 0)
                try:
                    lines = tails[wid].poll(srv.stream_read)
                except OSError as e:
                    log_stream_error(wid, e, "dropped from the admin stream")
                    dropped.add(wid)
                    continue
                if lines is None:
                    return None  # one file replaced or cut: the page reconnects, and reloads
                out.extend(e for e in (self._hit_event(n, raw, wid) for n, raw in lines) if e)
            first = False
            return out
        self._pump(look)

    @staticmethod
    def _hit_event(n: int, raw: bytes, workspace: str | None = None) -> str | None:
        """Line `n` of the hits file as an event, its id the line number (the hit's id); None for a line
        that does not parse (a crash's partial line), which still counts as a line. With `workspace`
        (the admin stream), the data says whose hit it is and the event id is `<workspace>:<n>`."""
        try:
            hit = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return None
        if not isinstance(hit, dict):
            return None
        canary = hit.get("canary") if isinstance(hit.get("canary"), dict) else {}
        kind = hit.get("kind")
        data = {"id": n, "kind": kind, "loud": kind in LOUD, "type": canary.get("type"),
                "frontend": hit.get("frontend"), "origin": hit_origin(hit), "html": hit_html(hit)}
        if workspace is None:
            return f"id: {n}\nevent: hit\ndata: {json.dumps(data)}\n\n"
        data["workspace"] = workspace
        return f"id: {workspace}:{n}\nevent: hit\ndata: {json.dumps(data)}\n\n"

    # ---- methods
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path, rest = self.route()
        if not path:
            return self.send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        if rest == "healthz":
            return self.send(HTTPStatus.OK, b"ok", "text/plain")
        if rest.startswith("static/"):
            return self.static(rest[len("static/"):])
        try:
            user = self.user()
        except (urllib.error.URLError, OSError, ValueError):
            return self.send(HTTPStatus.BAD_GATEWAY, message_page("Portal unavailable", "Coder did not answer; try again in a moment."))
        if user is None:
            if rest.endswith(".md") or rest.startswith("api/") or rest.endswith("hits.json") or rest.endswith("hits/events"):
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "not logged in"})
            return self.login_redirect(path)  # the page asked for, the hits page included
        if rest == "":
            return self.send(HTTPStatus.OK, list_page(self.store.listing(), user))
        # The admin routes first: "hits" is not a workspace id, so the <id> routes below never see it.
        if rest == "hits":
            return self.admin_page(user)
        if rest == "hits.json":
            return self.admin_json(user)
        if rest == "hits/events":
            return self.admin_events(user)
        if rest.endswith("/hits/events"):
            return self.hits_events(rest[:-len("/hits/events")], user)
        if rest.endswith("/hits.json"):
            return self.hits_json(rest[:-len("/hits.json")], user)
        if rest.endswith("/hits"):
            return self.hits_page(rest[:-len("/hits")], user)
        if rest == "runs":
            return self.send(HTTPStatus.OK, runs_page(user))
        if rest.startswith("api/"):
            return self.api(rest[len("api/"):])
        wid, is_md = (rest[:-3], True) if rest.endswith(".md") else (rest, False)
        if not UUID_RE.match(wid):
            return self.send(HTTPStatus.NOT_FOUND, message_page("Not found", "No such report.", user))
        meta = self.store.meta(wid)
        content = self.store.read(wid)
        if meta is None or content is None:
            return self.send(HTTPStatus.NOT_FOUND, message_page(
                "No report yet", "No report exists for this workspace. It is created when the workspace is first "
                "built; if the build is still running, come back in a minute.", user))
        if is_md:
            data, etag = content
            return self.send(HTTPStatus.OK, data, "text/markdown; charset=utf-8", {"ETag": etag})
        state = self.coder.workspace_state(self.token(), wid)
        return self.send(HTTPStatus.OK, editor_page(wid, meta, user, self.can_edit(meta, user), state,
                                                    self.store.last_saved(wid), content[0]))

    # ---- the API (the viewer is logged in; everything here is read-only)
    def api(self, rest: str):
        parts = rest.split("/")
        if parts == ["reports"]:
            return self.send_json(HTTPStatus.OK, {"reports": [public(r) for r in self.store.listing()]})
        if parts == ["runs"]:
            return self.send_json(HTTPStatus.OK, {"runs": self.runs.listing()})
        if len(parts) == 2 and parts[0] == "workspaces" and UUID_RE.match(parts[1]):
            wid = parts[1]
            meta = self.store.meta(wid)
            live = None
            if meta is not None and os.path.isfile(self.store._md(wid)):
                live = {**public(meta), "workspace_id": wid, "last_saved": self.store.last_saved(wid)}
            runs = self.runs.for_workspace(wid, (meta or {}).get("instance"))
            return self.send_json(HTTPStatus.OK, {"workspace_id": wid, "live_report": live, "runs": runs})
        if len(parts) < 2 or parts[0] != "runs" or not self.runs.exists(parts[1]):
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        rid, sub = parts[1], parts[2:]
        if not sub:
            return self.send_json(HTTPStatus.OK, self.runs.detail(rid))
        if sub == ["report.md"]:
            data = self.runs.raw(rid, "report.md")
            return self.send_bytes(data, "text/markdown; charset=utf-8")
        if len(sub) == 3 and sub[0] == "chats" and sub[1] in FRONTEND_DIRS:
            chat, ext = os.path.splitext(sub[2]) if sub[2].endswith((".md", ".json")) else (sub[2], "")
            if not CHAT_RE.match(chat):
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            if ext:
                data = self.runs.raw(rid, os.path.join(FRONTEND_DIRS[sub[1]], chat + ext))
                return self.send_bytes(data, "text/markdown; charset=utf-8" if ext == ".md" else "application/json")
            c = self.runs.chat(rid, sub[1], chat)
            if c is None:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return self.send_json(HTTPStatus.OK, c)
        if sub == ["agui", "agent-runs.jsonl"]:
            return self.send_bytes(self.runs.raw(rid, os.path.join("agui", "agent-runs.jsonl")), "application/x-ndjson")
        if len(sub) == 3 and sub[:2] == ["agui", "journals"] and sub[2].endswith(".jsonl") and UUID_RE.match(sub[2][:-6]):
            return self.send_bytes(self.runs.raw(rid, os.path.join("agui", "agui-journals", sub[2])), "application/x-ndjson")
        return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def send_bytes(self, data: bytes | None, ctype: str):
        if data is None:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        return self.send(HTTPStatus.OK, data, ctype)

    def do_PUT(self):
        path, rest = self.route()
        if not path or not rest.endswith(".md") or not UUID_RE.match(rest[:-3]):
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        wid = rest[:-3]
        if not self.same_origin():
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "cross-origin request"})
        try:
            user = self.user()
        except (urllib.error.URLError, OSError, ValueError):
            return self.send_json(HTTPStatus.BAD_GATEWAY, {"error": "Coder did not answer"})
        if user is None:
            return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "not logged in"})
        meta = self.store.meta(wid)
        if meta is None:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "no report for this workspace"})
        if not self.can_edit(meta, user):
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "only the owner and portal admins can edit this report"})
        if_match = self.headers.get("If-Match", "")
        if not if_match:
            return self.send_json(HTTPStatus.PRECONDITION_REQUIRED, {"error": "If-Match required"})
        data = self.body(MAX_BYTES)
        if data is None:
            return self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": f"the report must stay under {MAX_BYTES // 1000} kB"})
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "the report must be UTF-8 text"})
        try:
            etag = self.store.write(wid, data, if_match)
        except Conflict as c:
            return self.send_json(HTTPStatus.PRECONDITION_FAILED,
                                  {"error": "the report changed elsewhere; reload the page", "etag": c.args[0]})
        except FileNotFoundError:
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "no report for this workspace"})
        return self.send_json(HTTPStatus.OK, {"etag": etag, "saved": self.store.last_saved(wid)}, {"ETag": etag})

    def do_POST(self):
        path, rest = self.route()
        if not path or rest != "preview":
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        if not self.same_origin():
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "cross-origin request"})
        try:
            user = self.user()
        except (urllib.error.URLError, OSError, ValueError):
            return self.send_json(HTTPStatus.BAD_GATEWAY, {"error": "Coder did not answer"})
        if user is None:
            return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "not logged in"})
        data = self.body(MAX_BYTES)
        if data is None:
            return self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "too large"})
        text = data.decode("utf-8", errors="replace")
        return self.send(HTTPStatus.OK, render_markdown(text).encode(), "text/html; charset=utf-8")

    def body(self, limit: int) -> bytes | None:
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if n > limit:
            # Drain a bounded amount so the client gets the answer instead of a reset
            # mid-upload; past that, the connection is closed after the reply.
            left = min(n, 8 * limit)
            while left > 0:
                chunk = self.rfile.read(min(left, 65536))
                if not chunk:
                    break
                left -= len(chunk)
            self.close_connection = True
            return None
        return self.rfile.read(n)

    def static(self, name: str):
        ext = os.path.splitext(name)[1]
        if "/" in name or name.startswith(".") or ext not in STATIC_TYPES:
            return self.send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        try:
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                data = f.read()
        except OSError:
            return self.send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        self.send(HTTPStatus.OK, data, STATIC_TYPES[ext], {"Cache-Control": "public, max-age=300"})


def make_server(listen: str, reports_dir: str, coder_url: str, runs_dir: str | None = None,
                threat: ThreatScorer | None = None, hits_dir: str | None = None) -> ThreadingHTTPServer:
    host, _, port = listen.rpartition(":")
    handler = type("BoundHandler", (Handler,), {"store": Store(reports_dir), "coder": Coder(coder_url),
                                                "runs": Runs(runs_dir or os.path.join(os.path.dirname(reports_dir.rstrip("/")), "runs"), threat),
                                                "hits_dir": hits_dir})
    srv = ThreadingHTTPServer((host or "127.0.0.1", int(port)), handler)
    srv.daemon_threads = True
    srv.streams, srv.streams_lock = 0, threading.Lock()  # open event streams, at most stream_max
    srv.stream_max, srv.stream_seconds = STREAM_MAX, STREAM_SECONDS
    srv.stream_poll, srv.stream_ping, srv.stream_read = STREAM_POLL, STREAM_PING, STREAM_READ
    srv.stream_write_timeout = STREAM_WRITE_TIMEOUT
    srv.stream_status_refresh = STREAM_STATUS_REFRESH
    return srv


def main():
    listen = os.environ.get("LISTEN", "127.0.0.1:7090")
    reports_dir = os.environ.get("REPORTS_DIR", "/data-share/reports")
    hits_dir = os.environ.get("HITS_DIR", HITS_DIR)
    coder_url = os.environ.get("CODER_URL", "http://127.0.0.1:7080")
    runs_dir = os.environ.get("RUNS_DIR", "/data-share/runs")
    if not os.path.isdir(reports_dir):
        sys.exit(f"sperange-report: REPORTS_DIR {reports_dir} is not a directory")
    if not os.path.isdir(runs_dir):  # the runs browser is then empty, the reports still work
        print(f"sperange-report: RUNS_DIR {runs_dir} is not a directory; no archived runs to show", flush=True)
    threat = None
    embeddings_url, embeddings_key = os.environ.get("THREAT_EMBEDDINGS_URL"), os.environ.get("THREAT_EMBEDDINGS_KEY")
    if embeddings_url and embeddings_key:
        model_path = os.environ.get("THREAT_MODEL", os.path.join(os.path.dirname(os.path.abspath(__file__)), "threat_model.json"))
        try:
            threat = ThreatScorer(model_path, embeddings_url, embeddings_key,
                                  os.environ.get("THREAT_EMBEDDING_MODEL", "vllm/BAAI/bge-m3"))
        except (OSError, ValueError, KeyError) as e:  # the runs browser works without it
            print(f"sperange-report: no threat scores: {type(e).__name__}: {e}", flush=True)
    srv = make_server(listen, reports_dir, coder_url, runs_dir, threat, hits_dir)
    print(f"sperange-report: {reports_dir} and {runs_dir} on {listen}, Coder at {coder_url}, "
          f"hits in {hits_dir}, threat scores {'on' if threat else 'off'}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
