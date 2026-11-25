// A small board: cards move between columns by drag or by arrow keys, row
// actions appear on hover, a floating menu sits on a layer, and the detail
// panel resizes with a drag handle. Every pointer interaction has a keyboard
// path, and every control has a name.
const COLUMNS = [
  { id: "todo", title: "To do" },
  { id: "doing", title: "In progress" },
  { id: "done", title: "Done" },
];
const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

view({
  state: {
    cards: [
      { id: "c1", title: "Draft the release notes", col: "todo" },
      { id: "c2", title: "Review the sync fix", col: "doing" },
      { id: "c3", title: "Ship 1.4", col: "done" },
    ],
    selected: null,
    menu: null,
    panel: 320,
    base: 320,
  },

  commands: {
    move({ id, col }) { moveTo(id, col); return { moved: id, col }; },
  },

  render(s) {
    const open = s.cards.find(c => c.id === s.selected);
    return Page({ gap: 0, p: 0 },
      Row({ id: "board", grow: true, align: "stretch", gap: 0 },
        Row({ id: "columns", grow: true, align: "start", gap: 16, p: 24 },
          ...COLUMNS.map(col => column(s, col))),
        open && detail(s, open)));
  },
});

function moveTo(id, col, index) {
  setState(s => {
    const card = s.cards.find(c => c.id === id);
    if (!card) return null;
    const rest = s.cards.filter(c => c.id !== id);
    const siblings = rest.filter(c => c.col === col);
    const at = index === undefined ? siblings.length : clamp(index, 0, siblings.length);
    const before = siblings[at];
    const moved = { ...card, col };
    const i = before ? rest.indexOf(before) : rest.length;
    return { cards: [...rest.slice(0, i), moved, ...rest.slice(i)] };
  });
}

function nudge(card, dir) {
  const s = getState();
  const c = COLUMNS.findIndex(x => x.id === card.col);
  if (dir === "left" || dir === "right") {
    const next = COLUMNS[clamp(c + (dir === "left" ? -1 : 1), 0, COLUMNS.length - 1)];
    if (next.id !== card.col) moveTo(card.id, next.id);
    return;
  }
  const siblings = s.cards.filter(x => x.col === card.col);
  const i = siblings.indexOf(siblings.find(x => x.id === card.id));
  moveTo(card.id, card.col, clamp(i + (dir === "up" ? -1 : 1), 0, siblings.length - 1));
}

function column(s, col) {
  const cards = s.cards.filter(c => c.col === col.id);
  return Column({
    id: "col-" + col.id, w: 240, gap: 8, p: 8, radius: 8, bg: "inset",
    drop: { accepts: "card" },
    onDrop: ({ payload }) => moveTo(payload.id, col.id),
  },
    Row({ px: 4, h: 28 }, Label(col.title), Caption(String(cards.length))),
    ...cards.map(card => cardView(s, card)),
    cards.length === 0 && Caption("Drop cards here", { px: 4, py: 8 }));
}

function cardView(s, card) {
  const selected = s.selected === card.id;
  return Row({
    id: "card-" + card.id, label: card.title, group: "card-" + card.id,
    h: 40, px: 12, gap: 8, radius: 6, border: true,
    bg: selected ? "selected" : "canvas", hover: { borderColor: "secondary" },
    motion: { initial: { opacity: 0, y: 4 } },
    onClick: () => setState({ selected: selected ? null : card.id }),
    drag: { type: "card", payload: { id: card.id } },
    onNudge: ({ dir }) => nudge(card, dir),
  },
    Text(card.title, { grow: true, truncate: true }),
    Box({ id: "actions-" + card.id, opacity: s.menu === card.id ? 1 : 0,
      groupHover: { group: "card-" + card.id, opacity: 1 } },
      IconButton("more-horizontal", {
        id: "menu-" + card.id, label: "Actions for " + card.title,
        onClick: () => setState({ menu: s.menu === card.id ? null : card.id }),
      }),
      s.menu === card.id && menu(card)));
}

function menu(card) {
  return Column({
    id: "menu-panel-" + card.id, layer: 1, position: "absolute", top: 32, right: 0,
    w: 180, p: 4, gap: 2, radius: 8, bg: "canvas", border: true, shadow: "md",
    motion: { initial: { opacity: 0, y: -4 }, transition: { duration: 120 } },
  },
    ...COLUMNS.filter(c => c.id !== card.col).map(c =>
      Row({
        id: "move-" + card.id + "-" + c.id, h: 28, px: 8, radius: 6, hover: { bg: "inset" },
        onClick: () => { moveTo(card.id, c.id); setState({ menu: null }); },
      }, Text("Move to " + c.title))));
}

function detail(s, card) {
  return Row({ id: "detail", w: s.panel, shrink: false, align: "stretch", gap: 0, border: "left",
    motion: { initial: { opacity: 0, x: 16 } } },
    Box({
      id: "detail-resize", label: "Resize details", w: 6, cursor: "col-resize",
      hover: { bg: "rule" },
      drag: { type: "resize", axis: "x", follow: false },
      onDragStart: () => setState({ base: getState().panel }),
      onDrag: ({ dx }) => setState({ panel: clamp(getState().base - dx, 240, 560) }),
      onNudge: ({ dir, big }) => {
        if (dir !== "left" && dir !== "right") return;
        const step = (dir === "left" ? 1 : -1) * (big ? 32 : 8);
        setState({ panel: clamp(getState().panel + step, 240, 560) });
      },
    }),
    Column({ grow: true, p: 24, gap: 12 },
      Heading(card.title),
      Caption(COLUMNS.find(c => c.id === card.col).title),
      Button("Close", { onClick: () => setState({ selected: null }) })));
}
