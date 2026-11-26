// A standalone document. The editor owns its caret, history and scroll position.
const initial = [
    '# Field notes',
    'Walk the **north shore** before the afternoon tide.',
    '## On the trail',
    '- [x] Download the offline map',
    '- [ ] Sketch the old boathouse',
    '> The footbridge is the best place to see the inlet.',
].join('\n\n')

view({
    state: { blocks: fromMarkdown(initial) },
    render(s) {
        return Page(
            { align: 'center', gap: 0 },
            Reading(
                { grow: true, minH: 0 },
                BlockEditor({
                    id: 'document',
                    value: s.blocks,
                    grow: true,
                    placeholder: 'Write a note, or type / for blocks…',
                    onChange: (blocks) => setState({ blocks }),
                })
            )
        )
    },
    inspect: (s) => ({ markdown: toMarkdown(s.blocks) }),
})
