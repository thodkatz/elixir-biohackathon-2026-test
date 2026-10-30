"use client";
// The sessions sidebar: New chat, the list (pinned first, then newest) and each row's menu.
// Titles and tags are model or participant text: rendered as React text only, never as HTML.
import { useState } from "react";
import type { SessionMeta } from "../lib/sessions.ts";

type SidebarProps = {
  sessions: SessionMeta[];
  knownTags: string[];
  activeId: string | null;
  onNew: () => void;
  onOpen: (id: string) => void;
  onChanged: () => void;
  onDeleted: (id: string) => void;
  onError: (message: string) => void;
};

export function Sidebar({ sessions, activeId, onNew, onOpen }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  if (collapsed) {
    return (
      <nav className="spe-sidebar spe-sidebar-collapsed" aria-label="Sessions">
        <button type="button" className="spe-collapse" aria-label="Show sessions" onClick={() => setCollapsed(false)}>›</button>
      </nav>
    );
  }
  return (
    <nav className="spe-sidebar" aria-label="Sessions">
      <div className="spe-sidebar-top">
        <button type="button" className="spe-new" onClick={onNew}>New chat</button>
        <button type="button" className="spe-collapse" aria-label="Hide sessions" onClick={() => setCollapsed(true)}>‹</button>
      </div>
      <ul className="spe-list">
        {sessions.map((s) => (
          <li key={s.id} className={s.id === activeId ? "spe-row spe-row-active" : "spe-row"}>
            <button type="button" className="spe-row-open" onClick={() => onOpen(s.id)}
              aria-current={s.id === activeId ? "page" : undefined}>
              <span className="spe-row-title">
                {s.pinned && <span className="spe-pin" aria-label="pinned">📌 </span>}
                {s.title}
              </span>
              {s.tags.length > 0 && (
                <span className="spe-row-tags">
                  {s.tags.map((t) => <span key={t} className="spe-chip">{t}</span>)}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
      {sessions.length === 0 && <p className="spe-empty">No sessions yet.</p>}
      <p className="spe-note">Deleted sessions are kept in the run archive.</p>
    </nav>
  );
}
