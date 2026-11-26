async function change(op, args = {}) {
    if (getState().busy) return
    setState({ busy: true, error: '' })
    try {
        const notes = await host.call('notes', op, args)
        setState((s) => ({ notes, draft: op === 'save' && s.draft === args.text ? '' : s.draft }))
    } catch (e) {
        setState({ error: e.message })
    } finally {
        setState({ busy: false })
    }
}
view({
    state: { draft: '', notes: [], busy: false, error: '' },
    async init() {
        await change('list')
    },
    render(s) {
        const save = () => change('save', { text: getState().draft })
        return Page(
            Reading(
                { gap: 16 },
                Header({ title: 'Notes', subtitle: 'Local records' }),
                Form(
                    { id: 'note-form' },
                    Field(
                        { label: 'New note', for: 'note' },
                        Input({
                            id: 'note',
                            label: 'New note',
                            value: s.draft,
                            placeholder: 'Write a note…',
                            onChange: (draft) => setState({ draft }),
                            onSubmit: save,
                        })
                    ),
                    Row(
                        Button('Save note', {
                            id: 'save-note',
                            variant: 'primary',
                            disabled: s.busy || !s.draft.trim(),
                            onClick: save,
                        })
                    )
                ),
                s.error && ErrorMessage(s.error),
                Scroll(
                    { gap: 8 },
                    ...s.notes.map((note) =>
                        Row(
                            { justify: 'between' },
                            Text(note.text, { grow: true }),
                            IconButton('trash-2', {
                                id: 'remove-' + note.id,
                                label: 'Delete note',
                                disabled: s.busy,
                                onClick: () => change('remove', { id: note.id }),
                            })
                        )
                    )
                )
            )
        )
    },
    inspect: (s) => ({ notes: s.notes, busy: s.busy, error: s.error }),
})
