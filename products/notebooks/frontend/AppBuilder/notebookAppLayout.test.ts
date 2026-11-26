import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'

import {
    appSourceCells,
    emptyAppLayout,
    mergeAppCellOutput,
    moveAppBlock,
    normalizeAppLayout,
    pinAppCell,
    pinAppCells,
} from './notebookAppLayout'

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

it('persists a new identifier for multiline cells so app results merge back into the source', () => {
    const markdown = '<SQLV2 code="select 1"\n  height={600}\n/>'
    const pinned = pinAppCell(markdown, appSourceCells(markdown)[0].id)
    expect(appSourceCells(pinned.markdown)[0]).toMatchObject({
        id: pinned.nodeId,
        props: { nodeId: pinned.nodeId, code: 'select 1', height: 600 },
    })
    const output = `<SQLV2 nodeId="${pinned.nodeId}" code="select 1" runStatus="done" result={{"first_page":[[1]]}} />`
    expect(appSourceCells(mergeAppCellOutput(pinned.markdown, pinned.nodeId, output))[0]).toMatchObject({
        props: { nodeId: pinned.nodeId, height: 600, runStatus: 'done', result: { first_page: [[1]] } },
    })
})

it('preserves malformed cell source when pinning it or receiving a run result', () => {
    const markdown = '<SQLV2 code="select 1" "unparseable />'
    const pinned = pinAppCell(markdown, appSourceCells(markdown)[0].id)
    expect(pinned.markdown).toContain(markdown)
    expect(appSourceCells(pinned.markdown)[0].id).toBe(pinned.nodeId)

    const source = '<SQLV2 nodeId="query-1" code="select 1" "unparseable />'
    const output = '<SQLV2 nodeId="query-1" code="select 1" runStatus="done" />'
    expect(mergeAppCellOutput(source, 'query-1', output)).toBe(source)
})

it('links repeated paragraphs to distinct persistent sources in bulk', () => {
    const markdown = 'Repeated paragraph\n\nRepeated paragraph\n\n<SQLV2 nodeId="query-1" code="select 1" />'
    const cells = appSourceCells(markdown)
    const pinned = pinAppCells(
        markdown,
        cells.map((cell) => cell.id)
    )
    expect(new Set(pinned.nodeIds).size).toBe(3)
    expect(appSourceCells(pinned.markdown).map((cell) => cell.id)).toEqual(pinned.nodeIds)
    expect(pinned.nodeIds.slice(0, 2).every((id) => id.startsWith('phb-'))).toBe(true)
    expect(pinned.nodeIds[2]).toBe('query-1')
    expect(pinAppCells(pinned.markdown, pinned.nodeIds)).toEqual(pinned)
})

it('normalizes dropdown options at save time without changing the editable lines', () => {
    const layout = {
        ...emptyAppLayout(),
        blocks: [
            { id: 'region', kind: 'input' as const, tab_id: 'overview', options: [' Europe ', '', '  ', 'Asia', ''] },
        ],
    }
    expect(normalizeAppLayout(layout).blocks[0].options).toEqual(['Europe', 'Asia'])
    expect(layout.blocks[0].options).toEqual([' Europe ', '', '  ', 'Asia', ''])
})

it.each(['select 1', 'select 2'])('merges app execution output without overwriting source edits: %s', (code) => {
    const source = `# Keep this text\n\n<SQLV2 nodeId="query-1" code="${code}" height={600} hideInput={false} />\n\n<SQLV2 nodeId="query-2" code="select 3" />`
    const output =
        '<SQLV2 nodeId="query-1" code="select 1" height={220} hideInput={true} runId="run-2" runStatus="done" result={{"columns":["value"],"first_page":[[42]]}} />'
    const merged = mergeAppCellOutput(source, 'query-1', output)
    if (code === 'select 2') {
        expect(merged).toBe(source)
    } else {
        const cells = appSourceCells(merged)
        expect(cells).toHaveLength(3)
        expect(cells[1]).toMatchObject({
            props: {
                code,
                height: 600,
                hideInput: false,
                runId: 'run-2',
                runStatus: 'done',
                result: { first_page: [[42]] },
            },
        })
        expect(cells[2]).toMatchObject({ props: { nodeId: 'query-2', code: 'select 3' } })
        expect(merged).toContain('Keep this text')
        expect(mergeAppCellOutput(merged, 'query-1', output)).toBe(merged)
    }
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
