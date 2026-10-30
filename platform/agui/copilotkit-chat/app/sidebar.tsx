"use client";
// The sessions sidebar: New chat, the list (pinned first, then newest) and each row's menu.
// Titles and tags are model or participant text: rendered as React text only, never as HTML.
import { useState } from "react";
import type { KeyboardEvent } from "react";
import { removeSession, renamePatch, updateSession, withTag, withoutTag } from "../lib/client.ts";
import type { MetaPatch, SessionMeta } from "../lib/sessions.ts";

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

export function Sidebar({ sessions, knownTags, activeId, onNew, onOpen, onChanged, onDeleted, onError }: SidebarProps) {
  const [menuFor, setMenuFor] = useState<string | null>(null);
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
      <datalist id="spe-known-tags">
        {knownTags.map((t) => <option key={t} value={t} />)}
      </datalist>
      <ul className="spe-list">
        {sessions.map((s) => (
          <SessionRow
            key={s.id}
            session={s}
            active={s.id === activeId}
            menuOpen={menuFor === s.id}
            onToggleMenu={() => setMenuFor(menuFor === s.id ? null : s.id)}
            onCloseMenu={() => setMenuFor(null)}
            onOpen={() => onOpen(s.id)}
            onChanged={onChanged}
            onDeleted={() => onDeleted(s.id)}
            onError={onError}
          />
        ))}
      </ul>
      {sessions.length === 0 && <p className="spe-empty">No sessions yet.</p>}
      <p className="spe-note">Deleted sessions are kept in the run archive.</p>
    </nav>
  );
}

type RowProps = {
  session: SessionMeta;
  active: boolean;
  menuOpen: boolean;
  onToggleMenu: () => void;
  onCloseMenu: () => void;
  onOpen: () => void;
  onChanged: () => void;
  onDeleted: () => void;
  onError: (message: string) => void;
};

type Mode = "menu" | "rename" | "tags" | "delete";

function SessionRow({ session, active, menuOpen, onToggleMenu, onCloseMenu, onOpen, onChanged, onDeleted, onError }: RowProps) {
  const [mode, setMode] = useState<Mode>("menu");
  const [draft, setDraft] = useState("");

  const close = () => {
    setMode("menu");
    setDraft("");
    onCloseMenu();
  };
  // `stay`: the tag editor stays open for the next tag.
  const save = async (patch: MetaPatch | null, stay = false) => {
    if (patch) {
      try {
        await updateSession(session.id, patch);
        onChanged();
      } catch (e) {
        onError(e instanceof Error ? e.message : "Saving the change failed.");
      }
    }
    if (stay) setDraft("");
    else close();
  };
  const remove = async () => {
    try {
      await removeSession(session.id);
      onDeleted();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Deleting the session failed.");
    }
    close();
  };
  const keys = (onEnter: () => void) => (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") onEnter();
    if (event.key === "Escape") close();
  };

  return (
    <li className={active ? "spe-row spe-row-active" : "spe-row"}>
      {mode === "rename" && menuOpen ? (
        <input
          className="spe-rename"
          aria-label="Session title"
          autoFocus
          maxLength={200}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={keys(() => void save(renamePatch(draft, session.title)))}
        />
      ) : (
        <button type="button" className="spe-row-open" onClick={onOpen} aria-current={active ? "page" : undefined}>
          <span className="spe-row-title">
            {session.pinned && <span className="spe-pin" aria-label="pinned">📌 </span>}
            {session.title}
          </span>
          {session.tags.length > 0 && (
            <span className="spe-row-tags">
              {session.tags.map((t) => <span key={t} className="spe-chip">{t}</span>)}
            </span>
          )}
        </button>
      )}
      <button type="button" className="spe-row-menu" aria-label={`Menu for ${session.title}`} aria-expanded={menuOpen}
        onClick={() => { setMode("menu"); onToggleMenu(); }}>⋯</button>
      {menuOpen && mode === "menu" && (
        <div className="spe-menu" role="menu">
          <button type="button" role="menuitem" onClick={() => { setDraft(session.title); setMode("rename"); }}>Rename</button>
          <button type="button" role="menuitem" onClick={() => void save({ pinned: !session.pinned })}>
            {session.pinned ? "Unpin" : "Pin"}
          </button>
          <button type="button" role="menuitem" onClick={() => { setDraft(""); setMode("tags"); }}>Tags</button>
          <button type="button" role="menuitem" onClick={() => void save({ hidden: !session.hidden })}>
            {session.hidden ? "Unhide" : "Hide"}
          </button>
          <button type="button" role="menuitem" onClick={() => setMode("delete")}>Delete</button>
        </div>
      )}
      {menuOpen && mode === "tags" && (
        <div className="spe-menu">
          <span className="spe-row-tags">
            {session.tags.map((t) => (
              <span key={t} className="spe-chip">
                {t}
                <button type="button" aria-label={`Remove tag ${t}`} onClick={() => void save(withoutTag(session.tags, t), true)}>×</button>
              </span>
            ))}
          </span>
          <input
            aria-label="Add a tag"
            placeholder="add a tag"
            list="spe-known-tags"
            autoFocus
            maxLength={32}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={keys(() => void save(withTag(session.tags, draft), true))}
          />
        </div>
      )}
      {menuOpen && mode === "delete" && (
        <div className="spe-menu" role="alertdialog" aria-label="Delete session">
          <p>This removes it from your list. It is kept in the run archive.</p>
          <button type="button" onClick={() => void remove()}>Delete</button>
          <button type="button" onClick={close}>Cancel</button>
        </div>
      )}
    </li>
  );
}
