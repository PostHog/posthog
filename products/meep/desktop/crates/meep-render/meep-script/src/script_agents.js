// Agent execution and optional presentation. All I/O uses the view-scoped host.
"use strict";
var __agentSubscriptions = new Map(), __agentNextSubscription = 0;
var __agentBindings = new Map(), __agentParts = new Map();
function __agentPart(id) {
  if (!id) throw Error("Agent components need a stable id");
  if (!__agentParts.has(id)) {
    if (__agentParts.size >= 128) throw Error("Too many retained agent components");
    __agentParts.set(id, { open: false, follow: true, revision: 0, value: "", error: null });
  }
  return __agentParts.get(id);
}
function __agentDirty() { __effect(); __host_dirty(); }
function __agentReset() {
  for (const slot of __agentSubscriptions.values()) slot.active = false;
  __agentSubscriptions.clear(); __agentBindings.clear(); __agentParts.clear();
}
async function __agentSubscribe(id, callback, options) {
  __effect();
  if (typeof callback !== "function") throw Error("subscribe needs a callback");
  if (__agentSubscriptions.size >= 8) throw Error("At most eight agent subscriptions per view");
  const key = ++__agentNextSubscription, slot = { active: true };
  __agentSubscriptions.set(key, slot);
  const events = options && options.events;
  if (events && (!Array.isArray(events) || events.some(e => !["text", "thinking", "activity", "status", "snapshot", "error"].includes(e)))) {
    __agentSubscriptions.delete(key); throw Error("Unknown agent event filter");
  }
  const emit = event => { if (slot.active && (!events || events.includes(event.type) || event.type === "snapshot" || event.type === "error")) return callback(event); };
  let initial;
  try { initial = await __native("agents.watch", { id, waitMs: 0 }); }
  catch (e) { slot.active = false; __agentSubscriptions.delete(key); throw e; }
  const unsubscribe = () => { slot.active = false; __agentSubscriptions.delete(key); };
  let after = initial.sequence;
  try { if (initial.snapshot) await emit({ type: "snapshot", sequence: after, value: initial.snapshot }); }
  catch (e) { unsubscribe(); throw e; }
  if (initial.terminal) { unsubscribe(); return unsubscribe; }
  // One read in flight per subscription. No timer, polling render, or paid retry.
  (async () => {
    try {
      while (slot.active) {
        const page = await __native("agents.watch", { id, after });
        if (!slot.active) break;
        after = page.sequence;
        if (page.snapshot) await emit({ type: "snapshot", sequence: after, value: page.snapshot });
        for (const event of page.events || []) { if (!slot.active) break; await emit(event); }
        if (page.terminal) break;
      }
    } catch (e) { if (slot.active) { try { await emit({ type: "error", value: String(e.message || e) }); } catch (ignored) { console.error(ignored); } } }
    finally { unsubscribe(); }
  })();
  return unsubscribe;
}
async function __agentBind(id) {
  __effect();
  if (__agentBindings.has(id)) { const binding = __agentBindings.get(id); binding.references++; return binding.ready; }
  if (__agentBindings.size >= 8) throw Error("At most eight bound agent targets per view");
  const binding = { snapshot: null, error: null, version: 0, unsubscribe: null, references: 1 };
  __agentBindings.set(id, binding);
  binding.ready = (async () => {
    // Streamed events only say that something changed. Read the snapshot at
    // most once at a time, and once more if events arrived meanwhile, so a
    // long answer costs a handful of reads instead of one per text delta.
    const refresh = () => {
      binding.stale = true;
      if (binding.refreshing) return;
      binding.refreshing = true;
      __async((async () => {
        try {
          while (binding.stale && __agentBindings.get(id) === binding) {
            binding.stale = false;
            binding.snapshot = await __native("agents.get", { id });
            binding.version++; __agentDirty();
          }
        } catch (e) { binding.error = e.message; __agentDirty(); }
        finally { binding.refreshing = false; }
      })());
    };
    binding.unsubscribe = await __agentSubscribe(id, event => {
      if (event.type === "snapshot") { binding.snapshot = event.value; binding.version++; __agentDirty(); }
      else if (event.type === "error") { binding.error = event.value; binding.version++; __agentDirty(); }
      else refresh();
    });
    __agentDirty();
    return id;
  })().catch(e => { __agentBindings.delete(id); binding.error = e.message; throw e; });
  return binding.ready;
}
function __agentUnbind(id) {
  __effect();
  const binding = __agentBindings.get(id);
  if (binding && --binding.references > 0) return;
  if (binding && binding.unsubscribe) binding.unsubscribe();
  __agentBindings.delete(id);
}
host.agents = Object.freeze({
  catalog: () => __native("agents.catalog", {}),
  models: selection => __native("agents.models", { selection: selection || {} }),
  start: options => __native("agents.start", options || {}),
  execute: options => __native("agents.execute", options || {}),
  result: id => __native("agents.result", { id }),
  status: id => __native("agents.status", { id }),
  cancel: id => __native("agents.cancel", { id }),
  open: options => __native("agents.open", options || {}),
  send: (id, message) => __native("agents.send", Object.assign({}, message, { id })),
  list: options => __native("agents.list", options || {}),
  get: (id, options) => __native("agents.get", Object.assign({}, options, { id })),
  configure: (id, selection) => __native("agents.configure", { id, selection }),
  saveDraft: (id, text) => __native("agents.draft", { id, text }),
  remove: id => __native("agents.remove", { id }),
  subscribe: __agentSubscribe,
  bind: __agentBind,
  unbind: __agentUnbind,
});

// These functions compose the existing native elements. They add no element
// type, renderer branch, alternate event transport, or required app layout.
// They follow the app's own conversation: the person's words in a bubble on
// the right, the agent's as plain text, work folded into one quiet line.
const __agentStatusWords = { idle: "Ready", queued: "Queued", running: "Working…", completed: "Done", cancelled: "Stopped", interrupted: "Interrupted", error: "Failed" };
function __agentTime(at) {
  if (!at) return null;
  const d = new Date(at), h = d.getHours(), m = String(d.getMinutes()).padStart(2, "0");
  return (h % 12 || 12) + ":" + m + (h < 12 ? " AM" : " PM");
}
function __agentMark(status) {
  return status === "running" || status === "queued" ? Spinner({ size: 12 })
    : status === "error" ? Icon("circle-x", { size: 12, color: "danger" })
    : status === "cancelled" || status === "interrupted" ? Icon("circle-slash", { size: 12, color: "tertiary" })
    : Icon("check", { size: 12, color: "tertiary" });
}
function __agentText(value) { return typeof value === "string" ? value : JSON.stringify(value, null, 2); }
function AgentStatus(p) {
  p = p || {};
  const run = p.run || {}, status = p.status || run.status || "idle";
  const live = ["running", "queued"].includes(status);
  return Row({ id: p.id, gap: 6, align: "center", h: 28 },
    live ? Spinner({ size: 12 }) : null,
    Caption(p.label || __agentStatusWords[status] || status, { color: status === "error" ? "danger" : "secondary" }),
    p.onStop && live ? IconButton("square", { label: "Stop", onClick: p.onStop }) : null);
}
function ToolCall(p) {
  const b = p.block || p, id = p.id || b.id, slot = __agentPart(id);
  const open = p.open === undefined ? slot.open : p.open;
  const toggle = () => { if (p.onOpenChange) p.onOpenChange(!open); else { slot.open = !open; __agentDirty(); } };
  const detail = [b.input, b.output].filter(v => v !== undefined && v !== null && v !== "").map(__agentText);
  const title = b.title || b.text || "Tool call";
  return Column({ id, gap: 4 },
    Row({ id: id + ":row", gap: 6, align: "center", h: 24, onClick: detail.length ? toggle : undefined, label: (open ? "Hide " : "Show ") + title, radius: 4, hoverBg: detail.length ? "inset" : undefined, px: 4, ml: -4 },
      __agentMark(b.status),
      Caption(title, { color: "secondary", truncate: true }),
      detail.length ? Icon(open ? "chevron-down" : "chevron-right", { size: 12, color: "tertiary" }) : null),
    open && detail.length ? Row({ gap: 4, ml: 18, p: 8, radius: 6, bg: "inset", align: "start" },
      Column({ gap: 8, grow: true, minW: 0 }, detail.map(d => Mono(d.length > 4000 ? d.slice(0, 4000) + "…" : d))),
      IconButton("copy", { label: "Copy details", onClick: () => host.copy(detail.join("\n\n")) })) : null);
}
// One line for everything the agent did on the way to its answer, opened on
// request: "Thought · used 2 tools", or what it is doing right now.
function AgentActivity(p) {
  p = p || {};
  const id = p.id || "activity", slot = __agentPart(id);
  const blocks = (p.blocks || (p.run && p.run.blocks) || []).filter(b => b.kind !== "text");
  if (!blocks.length) return null;
  const live = blocks.find(b => ["running", "queued"].includes(b.status));
  const tools = blocks.filter(b => b.kind === "tool").length, thought = blocks.some(b => b.kind === "thinking");
  const failed = blocks.some(b => b.status === "error");
  const summary = live ? (live.kind === "thinking" ? "Thinking…" : (live.title || "Working") + "…")
    : [thought ? "Thought" : null, tools ? "used " + tools + (tools === 1 ? " tool" : " tools") : null].filter(Boolean).join(" · ").replace(/^u/, thought ? "u" : "U");
  const toggle = () => { slot.open = !slot.open; __agentDirty(); };
  return Column({ id, gap: 4 },
    Row({ id: id + ":summary", gap: 6, align: "center", h: 24, onClick: toggle, label: (slot.open ? "Hide" : "Show") + " the agent's steps", radius: 4, hoverBg: "inset", px: 4, ml: -4 },
      live ? Spinner({ size: 12 }) : failed ? Icon("circle-x", { size: 12, color: "danger" }) : null,
      Caption(summary, { color: "secondary" }),
      Icon(slot.open ? "chevron-down" : "chevron-right", { size: 12, color: "tertiary" })),
    slot.open ? Column({ gap: 2, pl: 8, borderColor: "rule", border: "left" }, blocks.map((b, i) =>
      ToolCall({ id: id + ":" + (b.id || i), block: b.kind === "thinking" ? { title: "Thinking", status: b.status, output: b.text } : b }))) : null);
}
function ChatMessage(p) {
  const m = p.message || p, id = p.id || m.id, slot = __agentPart(id);
  const blocks = m.blocks || [], time = __agentTime(m.createdAt);
  if (m.role === "user") {
    return Column({ id, gap: 4, align: "end" },
      Column({ px: 12, py: 8, radius: 8, bg: "inset", maxW: "85%" },
        Text(String(m.text || ""), { selectable: true })),
      time ? Caption(time, { color: "secondary" }) : null);
  }
  const text = blocks.length ? blocks.filter(b => b.kind === "text").map(b => b.text).join("\n\n") : (m.text || "");
  const live = m.status && ["running", "queued"].includes(m.status);
  const copy = () => { host.copy(text); slot.copied = true; __agentDirty(); setTimeout(() => { slot.copied = false; __agentDirty(); }, 1500); };
  return Column({ id, gap: 8 },
    p.showActivity === false ? null : AgentActivity({ id: id + ":activity", blocks }),
    text ? Markdown(text, { id: id + ":text", selectable: true }) : null,
    live && !blocks.some(b => b.kind !== "text" && ["running", "queued"].includes(b.status)) ? AgentStatus({ status: m.status }) : null,
    m.error ? ErrorMessage(m.error) : null,
    !live && (text || time) ? Row({ gap: 4, align: "center" },
      m.agent || time ? Caption([m.agent, time].filter(Boolean).join(" · "), { color: "secondary" }) : null,
      text ? IconButton(slot.copied ? "check" : "copy", { label: slot.copied ? "Copied" : "Copy message", onClick: copy }) : null) : null);
}
function ChatTranscript(p) {
  const binding = p.session && __agentBindings.get(p.session), snapshot = binding && binding.snapshot;
  const messages = p.messages || (snapshot && snapshot.messages) || [];
  const slot = __agentPart(p.id);
  const change = event => { const follow = event.max - event.y <= 12; if (follow !== slot.follow) { slot.follow = follow; __agentDirty(); } if (p.onScroll) p.onScroll(event); };
  return Column({ id: p.id, grow: true, minH: 0, gap: 8 },
    Scroll({ id: p.id + ":scroll", grow: true, gap: 24, px: 12, py: 16, onScroll: change,
      scrollTo: slot.follow ? "end" : undefined, scrollRevision: (binding ? binding.version : (p.revision || messages.length)) + ":" + slot.revision },
      messages.length ? messages.map(m => ChatMessage({ id: p.id + ":" + m.id, message: m, showActivity: p.showActivity })) :
        Column({ grow: true, justify: "center", align: "center", py: 48 }, Caption(p.emptyState || "Ask anything to start.", { color: "secondary" }))),
    !slot.follow ? Row({ justify: "center" }, Button("Latest", { icon: "arrow-down", onClick: () => { slot.follow = true; slot.revision++; __agentDirty(); } })) : null);
}
// The app's own agent, model and effort selector (ModelSelector), with the
// app's catalog. profiles/models/efforts are accepted for compatibility and
// ignored: the window knows the real ones.
function AgentPicker(p) {
  return ModelSelector({ id: p.id, selection: p.selection || {}, onChange: p.onChange, disabled: p.disabled, placement: p.placement });
}
function ChatComposer(p) {
  const slot = __agentPart(p.id), binding = p.session && __agentBindings.get(p.session);
  const snapshot = binding && binding.snapshot, run = p.run || (snapshot && snapshot.run);
  const running = run && ["queued", "running"].includes(run.status);
  if (slot.session !== p.session) {
    const keepFirstDraft = slot.session === undefined && !!slot.value;
    slot.session = p.session; slot.draftRestored = false;
    if (!keepFirstDraft) slot.value = "";
  }
  // A bound session's snapshot usually arrives after the first render: restore
  // its saved draft once it does, unless the person has started typing.
  if (snapshot && !slot.draftRestored) { slot.draftRestored = true; if (!slot.value) slot.value = snapshot.draft || ""; }
  const value = p.value === undefined ? slot.value : p.value;
  const change = text => { if (p.onChange) p.onChange(text); else { slot.value = text; __agentDirty(); }
    if (p.session) { slot.pendingDraft = text; if (!slot.savingDraft) __async((async () => {
      slot.savingDraft = true;
      try { while (slot.pendingDraft !== undefined) { const draft = slot.pendingDraft; slot.pendingDraft = undefined; await host.agents.saveDraft(p.session, draft); } }
      catch (e) { slot.error = e.message; __agentDirty(); } finally { slot.savingDraft = false; }
    })()); } };
  const send = async (delivery, text = value) => {
    if (!text.trim() || slot.sending) return;
    slot.sending = true; slot.error = null; __agentDirty();
    const clientMessageId = slot.clientMessageId || (slot.clientMessageId = p.id + ":" + Date.now() + ":" + (++__agentNextSubscription));
    try {
      if (p.onSend) await p.onSend(text, { delivery, clientMessageId });
      else if (p.session) await host.agents.send(p.session, { text, context: p.context || null, delivery,
        execution: p.execution || "foreground", clientMessageId });
      else throw Error("Provide onSend or a bound session");
      slot.clientMessageId = null; change("");
    } catch (e) { slot.error = e.message; }
    finally { slot.sending = false; __agentDirty(); }
  };
  const ready = !!value.trim() && !slot.sending && !p.disabled;
  // One surface, like the app's own composer: the field, then the agent
  // controls on the left and the round send action on the right.
  return Column({ id: p.id, gap: 4 },
    Column({ p: 8, gap: 4, border: true, borderColor: "rule", radius: 8, bg: "canvas" },
      Textarea({ id: p.id + ":input", bare: true, label: p.label || "Message", placeholder: p.placeholder || (running ? "Add to the queue or steer…" : "Message…"), value, rows: p.rows || 2, disabled: p.disabled,
        submitOnEnter: p.submitOnEnter !== false, onSubmit: text => send(running ? "queue" : "send", text), onChange: change }),
      Row({ gap: 4, align: "center" },
        p.controls || null,
        Spacer(),
        running && value.trim() ? Button("Steer", { disabled: slot.sending, onClick: () => send("steer"), label: "Send now, replacing the current work" }) : null,
        running ? IconButton("square", { label: "Stop", onClick: p.onStop || (() => host.agents.cancel(run.id)) }) : null,
        IconButton("arrow-up", { variant: "primary", label: running ? "Queue message" : "Send message", disabled: !ready, onClick: () => send(running ? "queue" : "send") }))),
    slot.error ? ErrorMessage(slot.error) : null);
}
function ChatSessionList(p) {
  const sessions = p.sessions || [];
  return Column({ id: p.id, gap: 2 }, sessions.length ? sessions.map(s => Row({ id: p.id + ":" + s.id, gap: 4, align: "center", h: 32, px: 8, radius: 6,
      bg: p.selected === s.id ? "selected" : undefined, hoverBg: p.selected === s.id ? undefined : "inset",
      onClick: () => p.onSelect && p.onSelect(s.id), label: s.title || "New conversation" },
    Text(s.title || "New conversation", { grow: true, truncate: true }),
    p.onRemove ? IconButton("trash", { label: "Delete conversation", onClick: () => p.onRemove(s.id) }) : null)) :
    Caption("No earlier conversations.", { color: "secondary", py: 8 }));
}
function Chat(p) {
  const slot = __agentPart(p.id);
  if (slot.providedSession !== p.session) { slot.providedSession = p.session; slot.activeSession = p.session; }
  const sessionId = slot.activeSession;
  const binding = sessionId && __agentBindings.get(sessionId);
  const snapshot = binding && binding.snapshot;
  const managed = !!sessionId || (!p.onSend && !p.messages);
  const action = async fn => { try { slot.error = null; await fn(); } catch (e) { slot.error = e.message; } __agentDirty(); };
  const send = p.onSend || (async (text, metadata) => {
    let id = slot.activeSession;
    if (!id) {
      const session = await host.agents.open(Object.assign({}, p.options || {}, { selection: pending }));
      await host.agents.bind(session.id); id = session.id; slot.activeSession = id;
      if (p.onSessionChange) p.onSessionChange(id);
    }
    try { return await host.agents.send(id, Object.assign({}, metadata, { text, context: p.context || null, execution: p.execution || "foreground" })); }
    catch (e) { await host.agents.saveDraft(id, text); throw e; }
  });
  // Before a session exists the choice waits here and opens the session.
  const pending = slot.selection || (p.options && p.options.selection) || {};
  const choose = async selection => {
    if (!sessionId) { slot.selection = selection; return; }
    await host.agents.configure(sessionId, selection);
    if (binding) binding.snapshot = await host.agents.get(sessionId);
  };
  const controls = AgentPicker({ id: p.id + ":picker", placement: "above", selection: snapshot ? snapshot.selection || {} : pending,
    disabled: !!(snapshot && snapshot.run), onChange: s => action(() => choose(s)) });
  return Column({ id: p.id, grow: true, minH: 0, gap: 8 },
    Row({ gap: 4, align: "center", h: 32 }, Text(p.title || (snapshot && snapshot.title) || "New conversation", { weight: "semibold", grow: true, truncate: true }),
      managed || p.onHistory ? IconButton("list-clock", { label: slot.history ? "Hide history" : "History", onClick: () => action(async () => { slot.sessions = p.onHistory ? await p.onHistory() : (await host.agents.list()).items; slot.history = !slot.history; }) }) : null,
      managed || p.onNew ? IconButton("square-pen", { label: "New conversation", onClick: () => action(async () => { if (p.onNew) { await p.onNew(); return; } const s = await host.agents.open(sessionId ? { from: sessionId } : (p.options || {})); if (sessionId) host.agents.unbind(sessionId); await host.agents.bind(s.id); slot.activeSession = s.id; if (p.onSessionChange) p.onSessionChange(s.id); }) }) : null),
    slot.history ? ChatSessionList({ id: p.id + ":history", sessions: slot.sessions || [], selected: sessionId,
      onSelect: s => action(async () => { if (sessionId) host.agents.unbind(sessionId); await host.agents.bind(s); slot.activeSession = s; slot.history = false; if (p.onSessionChange) p.onSessionChange(s); }),
      onRemove: s => action(async () => { await host.agents.remove(s); host.agents.unbind(s); if (slot.activeSession === s) { slot.activeSession = null; if (p.onSessionChange) p.onSessionChange(null); } slot.sessions = (await host.agents.list()).items; }) }) : null,
    ChatTranscript({ id: p.id + ":transcript", session: sessionId, messages: p.messages, emptyState: p.emptyState, showActivity: p.showActivity }),
    binding && binding.error ? ErrorMessage(binding.error) : null,
    slot.error ? ErrorMessage(slot.error) : null,
    snapshot && snapshot.queued && snapshot.queued.length ? Column({ gap: 2 }, snapshot.queued.map((r, i) => Row({ gap: 6, align: "center", h: 28, px: 8, radius: 6, bg: "inset" },
      Icon("clock", { size: 12, color: "tertiary" }),
      Caption(r.prompt || "Queued message " + (i + 1), { color: "secondary", grow: true, truncate: true }),
      IconButton("x", { label: "Remove from queue", onClick: () => host.agents.cancel(r.id) })))) : null,
    ChatComposer({ id: p.id + ":composer", session: sessionId, context: p.context, execution: p.execution, placeholder: p.placeholder,
      value: p.draft, onChange: p.onDraftChange, onSend: send, controls }));
}
