import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'

import { appSourceCells, emptyAppLayout, moveAppBlock, pinAppCell } from './notebookAppLayout'

it('keeps an app source attached to a text cell after its content changes', () => {
    const markdown = '## Original title\n\nSome context'
    const node = appSourceCells(markdown)[0]
    const pinned = pinAppCell(markdown, node.id)
    const edited = parseMarkdownNotebook(pinned.markdown.replace('Original title', 'Updated title'))
    expect(edited.nodes[0].id).toBe(pinned.nodeId)
    expect(edited.nodes).toHaveLength(2)
    expect(pinAppCell(pinned.markdown, pinned.nodeId)).toEqual(pinned)
})

it('preserves executable cell identifiers and code when linking a source', () => {
    const markdown = '<SQLV2 nodeId="query-1" code="select 1" />'
    expect(appSourceCells(markdown)[0].id).toBe('query-1')
    expect(appSourceCells(markdown.replace('select 1', 'select 2'))[0].id).toBe('query-1')
    expect(pinAppCell(markdown, 'query-1')).toEqual({ markdown, nodeId: 'query-1' })
})

it('moves only the requested component and keeps components on their target tab', () => {
    const layout = {
        ...emptyAppLayout(),
        tabs: [
            { id: 'one', title: 'One' },
            { id: 'two', title: 'Two' },
        ],
        blocks: [
            { id: 'a', kind: 'text' as const, tab_id: 'one', text: 'A' },
            { id: 'b', kind: 'text' as const, tab_id: 'one', text: 'B' },
            { id: 'c', kind: 'text' as const, tab_id: 'two', text: 'C' },
        ],
    }
    const moved = moveAppBlock(layout, 'a', 'c')
    expect(moved.blocks.map((block) => block.id)).toEqual(['b', 'a', 'c'])
    expect(moved.blocks[1].tab_id).toBe('two')
    expect(layout.blocks[0].tab_id).toBe('one')
    expect(moveAppBlock(layout, 'unknown', 'c')).toBe(layout)
})
