"""Compare every AG-UI session as the chat showed it before destroy.yml with the final archive
(docs/knowledge/agui-coder-e2e-check.md, *The final archive*). Usage: python3 agui-archive-compare.py <snapshot dir> <run>/agui"""
import json, sys, glob, os, filecmp
S, R = sys.argv[1], sys.argv[2]
sessions = json.load(open(f"{S}/pre/sessions.json"))
arch = {}
for f in glob.glob(f"{R}/chats/*.json"):
    d = json.load(open(f)); arch[d["id"]] = d
bad = 0
for s in sessions:
    sid = s["id"]
    api = json.load(open(f"{S}/pre/api/{sid}.json"))
    j_same = filecmp.cmp(f"{S}/pre/journals/{sid}.jsonl", f"{R}/agui-journals/{sid}.jsonl", shallow=False)
    runs = sum(1 for l in open(f"{R}/agui-journals/{sid}.jsonl") if '"run_end"' in l)
    a = arch.get(sid)
    am = a["chat"]["messages"] if a else []
    def pick(ms, roles=("user", "assistant")):
        return [(m["role"], (m.get("content") or "").strip()) for m in ms if m["role"] in roles]
    au, xu = pick(api["messages"], ("user",)), pick(am, ("user",))
    # assistant texts: compare the final text of each turn by content set
    aa = [c for r, c in pick(api["messages"], ("assistant",)) if c]
    xa = [(m.get("content") or "") + json.dumps(m.get("output", []), ensure_ascii=False) for m in am if m["role"] == "assistant"]
    ok = j_same and a is not None and au == xu and all(any(t in x or json.dumps(t, ensure_ascii=False)[1:-1] in x for x in xa) for t in aa) and a["title"] == s["title"]
    bad += not ok
    print(f"{'OK ' if ok else 'BAD'} {sid[:8]} runs={runs} journal_identical={j_same} users api/arch={len(au)}/{len(xu)} "
          f"assistant texts api/arch={len(aa)}/{len(xa)} title_eq={a and a['title']==s['title']}")
print("archived sessions:", len(arch), "listed:", len(sessions), "mismatches:", bad)
