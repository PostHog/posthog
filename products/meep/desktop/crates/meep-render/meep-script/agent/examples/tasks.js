// Issues from a connected MCP tracker in a quiet reading layout.
// Arrow keys move the selection; the list is virtualized.
// SOURCE and the tool name are placeholders: use the connection name and tool
// that sources_list reports for the user's tracker.
const SOURCE = "tracker";
view({
  needs: [{ source: SOURCE, tools: ["list_issues"] }],
  state: { rows: [], selected: null, loading: false, error: null },
  async init() { await reload(); },
  keys: {
    down: () => move(1),
    up: () => move(-1),
  },
  commands: {
    refresh() { reload(); },
    select({ index }) { setState({ selected: Number.isInteger(index) && index < getState().rows.length ? index : null }); },
  },
  inspect: (s) => ({ rows: s.rows.length, selected: s.selected, loading: s.loading }),
  render(s) {
    const item = s.selected === null ? null : s.rows[s.selected];
    return Page({ align: "center" },
      Reading({ gap: 0 },
        Header({ title: "Issues", subtitle: s.loading ? "Refreshing…" : plural(s.rows.length, "issue") },
          IconButton("refresh-cw", { label: "Refresh", disabled: s.loading, onClick: reload })),
        s.error ? ErrorMessage(s.error) : null,
        s.rows.length === 0 ? (s.loading ? Loading() : Empty("Nothing on your list", "Issues from your connected tracker will appear here.")) : null,
        List({
          id: "issues",
          count: s.rows.length,
          scrollTo: s.selected,
          row: (i) => ListRow(s.rows[i].title || "Untitled", (s.rows[i].status || "No status") + " · " + (s.rows[i].project || "Unassigned"), {
            id: "item-" + i,
            selected: s.selected === i,
            onClick: () => setState({ selected: i }),
          }),
        }),
        item ? Scroll({ id: "selected-detail", gap: 10, pt: 20, border: "top", maxH: 180, grow: false },
          Text(item.title || "Untitled", { weight: "medium" }),
          Caption(item.description || "No description")) : null,
      ));
  },
});

async function reload() {
  if (getState().loading) return;
  setState({ loading: true, error: null });
  try {
    const result = await host.call(SOURCE, "list_issues", { limit: 200 });
    const rows = result.issues || [];
    setState({ rows, loading: false, selected: valid(getState().selected, rows) });
  } catch (e) {
    setState({ loading: false, error: e.message });
  }
}
function move(delta) {
  const { rows, selected } = getState();
  if (!rows.length) return;
  const from = selected === null ? (delta > 0 ? -1 : rows.length) : selected;
  setState({ selected: Math.max(0, Math.min(rows.length - 1, from + delta)) });
}
function valid(index, rows) { return index !== null && index < rows.length ? index : null; }
function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }
