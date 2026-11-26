// Notes kept by an MCP source: a retained draft, a mutation, and a
// virtualized list. The draft survives live edits and restarts.
// SOURCE and the tool names are placeholders: use the connection name and tools
// that sources_list reports for the user's notes service.
const SOURCE = 'notes'
view({
    needs: [{ source: SOURCE, tools: ['list_notes', 'add_note'] }],
    state: { notes: [], draft: '', loading: false, saving: false, error: null },
    async init() {
        await reload()
    },
    commands: {
        refresh() {
            reload()
        },
        add_note(args) {
            return add(typeof args === 'string' ? args : args.text)
        },
    },
    inspect: (s) => ({ count: s.notes.length, recent: s.notes.slice(0, 10), saving: s.saving }),
    render(s) {
        return Page(
            { align: 'center' },
            Reading(
                { gap: 0 },
                Header(
                    { title: 'Notes', subtitle: plural(s.notes.length, 'note') },
                    IconButton('refresh-cw', { label: 'Refresh notes', disabled: s.loading, onClick: reload })
                ),
                Row(
                    { p: 8, mb: 20, gap: 8, radius: 6, bg: 'inset' },
                    Box(
                        { grow: true },
                        Input({
                            id: 'draft',
                            value: s.draft,
                            label: 'Write a note',
                            placeholder: 'Write a note…',
                            onChange: (draft) => setState({ draft }),
                            onSubmit: (text) => add(text),
                        })
                    ),
                    Button(s.saving ? 'Saving…' : 'Add', {
                        variant: 'primary',
                        disabled: s.saving || !s.draft.trim(),
                        onClick: () => add(getState().draft),
                    })
                ),
                s.error ? Text(s.error, { color: 'secondary', pb: 16 }) : null,
                s.notes.length === 0 && !s.error
                    ? Text(s.loading ? 'Loading notes…' : 'Your notes will appear here.', {
                          color: 'secondary',
                          pt: 24,
                      })
                    : null,
                List({
                    id: 'notes',
                    count: s.notes.length,
                    row: (i) => ListRow(s.notes[i].text, when(s.notes[i].created), { id: 'note-' + i }),
                })
            )
        )
    },
})

async function reload() {
    setState({ loading: true })
    try {
        const result = await host.call(SOURCE, 'list_notes', {})
        setState({ notes: result.notes || [], loading: false, error: null })
    } catch (e) {
        setState({ loading: false, error: e.message })
    }
}
async function add(text) {
    if (getState().saving) throw new Error('A note is already being saved.')
    if (!text || !text.trim()) throw new Error('Write something first.')
    setState({ saving: true, error: null })
    try {
        await host.call(SOURCE, 'add_note', { text })
        // Clear only if the user has not started another note meanwhile.
        setState((s) => ({ saving: false, draft: s.draft === text ? '' : s.draft }))
        await reload()
    } catch (e) {
        setState({ saving: false, error: e.message })
    }
    return { accepted: true }
}
function when(iso) {
    const date = new Date(iso)
    if (isNaN(date)) return ''
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    const pad = (n) => String(n).padStart(2, '0')
    return months[date.getMonth()] + ' ' + date.getDate() + ' · ' + pad(date.getHours()) + ':' + pad(date.getMinutes())
}
function plural(n, word) {
    return n + ' ' + word + (n === 1 ? '' : 's')
}
