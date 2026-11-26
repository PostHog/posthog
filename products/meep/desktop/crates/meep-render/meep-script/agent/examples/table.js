// Keep records outside state; native cells need no JavaScript while scrolling.
view({
    state: { query: '', sort: [], selected: null, collapsed: [] },
    init() {
        if (!host.data.count('work'))
            host.data.set(
                'work',
                Array.from({ length: 400 }, (_, i) => ({
                    id: i,
                    title: 'Record ' + (i + 1),
                    owner: 'Developer ' + ((i % 18) + 1),
                    status: ['Todo', 'Doing', 'Done'][i % 3],
                    team: 'Team ' + ((i % 7) + 1),
                    score: (i * 7) % 100,
                    updated: '2026-11-10',
                    ok: i % 8,
                    fail: i % 2,
                    pending: i % 3,
                })),
                { key: 'id' }
            )
    },
    badge: (s, data) => data.count('work', { where: [{ field: 'status', op: 'eq', value: 'Todo' }] }),
    keys: { down: () => move(1), up: () => move(-1), 'cmd-f': () => host.focus('search') },
    render(s) {
        return Page(
            Header({ title: 'Work queue', subtitle: host.data.count('work') + ' records' }),
            Input({
                id: 'search',
                placeholder: 'Search records',
                value: s.query,
                onChange: (query) => setState({ query }),
            }),
            Table({
                id: 'work',
                data: 'work',
                query: query(s),
                groupBy: 'team',
                collapsed: s.collapsed,
                selected: s.selected,
                columns: [
                    { field: 'title', title: 'Title', grow: true },
                    { field: 'owner', title: 'Owner', w: 130 },
                    {
                        field: 'status',
                        title: 'Status',
                        kind: 'badge',
                        w: 90,
                        colors: { Todo: 'secondary', Doing: 'accent', Done: 'positive' },
                    },
                    { field: 'score', title: 'Score', kind: 'number', align: 'right', w: 70 },
                    { field: 'updated', title: 'Updated', kind: 'date', w: 110 },
                    { title: 'Checks', kind: 'checks', w: 130 },
                ],
                onRowClick: (selected) => setState({ selected }),
                onSort: (sort) => setState({ sort: [sort] }),
                onToggleGroup: (group) =>
                    setState({
                        collapsed: s.collapsed.includes(group)
                            ? s.collapsed.filter((g) => g !== group)
                            : s.collapsed.concat(group),
                    }),
            })
        )
    },
})
function query(s) {
    return { text: { value: s.query, fields: ['title', 'owner'] }, sort: s.sort }
}
function move(delta) {
    const s = getState(),
        rows = host.data.rows('work', Object.assign(query(s), { limit: 2000 }))
    const visible = rows.filter((r) => !s.collapsed.includes(r.team))
    const i = visible.findIndex((r) => r.id === s.selected)
    if (visible.length) setState({ selected: visible[Math.max(0, Math.min(visible.length - 1, i + delta))].id })
}
