import { Editor, JSONContent } from '@tiptap/core'

import { insertBlock } from './emailCommands'
import { buildEmailExtensions } from './emailExtensions'

const text = (value: string): JSONContent => ({ type: 'paragraph', content: [{ type: 'text', text: value }] })
const box = (type: string, ...content: JSONContent[]): JSONContent => ({ type, content })
const columns = box('emailColumns', box('emailColumn', text('In column')))
const section = (...content: JSONContent[]): JSONContent => box('emailSection', ...content)

/** The document's blocks as text, such as `emailSection(paragraph emailColumns(…))`. */
function outline(node: JSONContent): string {
    const inner = (node.content ?? []).filter((child) => child.type !== 'text').map(outline)
    return inner.length ? `${node.type}(${inner.join(' ')})` : node.type!
}

describe('emailCommands', () => {
    it.each<[string, JSONContent[], string, JSONContent, string]>([
        [
            'columns into a section',
            [section(text('In section'))],
            'In section',
            columns,
            'emailSection(paragraph emailColumns(emailColumn(paragraph)))',
        ],
        [
            'columns after the columns around the cursor, in the same section',
            [section(columns, text('Last'))],
            'In column',
            columns,
            'emailSection(emailColumns(emailColumn(paragraph)) emailColumns(emailColumn(paragraph)) paragraph)',
        ],
        [
            'a section after the section around the cursor',
            [section(text('In section'))],
            'In section',
            section(text('New')),
            'emailSection(paragraph) emailSection(paragraph)',
        ],
        [
            'a section after columns in a section',
            [section(columns)],
            'In column',
            section(text('New')),
            'emailSection(emailColumns(emailColumn(paragraph))) emailSection(paragraph)',
        ],
        [
            'a block into the column around the cursor',
            [columns],
            'In column',
            text('New'),
            'emailColumns(emailColumn(paragraph paragraph))',
        ],
    ])('inserts %s', (_, content, cursorIn, block, expected) => {
        const editor = new Editor({ extensions: buildEmailExtensions(''), content: { type: 'doc', content } })
        editor.state.doc.descendants((node, pos) => {
            if (node.text === cursorIn) {
                editor.commands.setTextSelection(pos + 1)
            }
        })
        insertBlock(editor, block)

        expect(editor.getJSON().content!.map(outline).join(' ')).toMatch(
            new RegExp(`^${expected.replace(/[()]/g, '\\$&')}( paragraph)?$`)
        )
        expect(() => editor.state.doc.check()).not.toThrow()
        editor.destroy()
    })

    it.each<[string, JSONContent[], string, string, string]>([
        [
            'wraps every selected block',
            [text('One'), text('Two'), text('End')],
            'One',
            'Two',
            'emailSection(paragraph paragraph) paragraph',
        ],
        [
            'goes after the block when only one is selected',
            [text('One'), text('End')],
            'One',
            'One',
            'paragraph emailSection(paragraph) paragraph',
        ],
        [
            'goes after the section the selected blocks are in',
            [section(text('One'), text('Two')), text('End')],
            'One',
            'Two',
            'emailSection(paragraph paragraph) emailSection(paragraph) paragraph',
        ],
        [
            'goes after a selected section',
            [section(text('One')), text('Two'), text('End')],
            'One',
            'Two',
            'emailSection(paragraph) emailSection(paragraph) paragraph paragraph',
        ],
        [
            'goes after the columns the selected blocks are in',
            [box('emailColumns', box('emailColumn', text('One'), text('Two'))), text('End')],
            'One',
            'Two',
            'emailColumns(emailColumn(paragraph paragraph)) emailSection(paragraph) paragraph',
        ],
        [
            'goes after the quote the selected blocks are in',
            [box('blockquote', text('One'), text('Two')), text('End')],
            'One',
            'Two',
            'blockquote(paragraph paragraph) emailSection(paragraph) paragraph',
        ],
    ])('a section added to a selection %s', (_, content, first, last, expected) => {
        const editor = new Editor({ extensions: buildEmailExtensions(''), content: { type: 'doc', content } })
        const at: Record<string, number> = {}
        editor.state.doc.descendants((node, pos) => {
            if (node.text) {
                at[node.text] = pos
            }
        })
        editor.commands.setTextSelection({ from: at[first], to: at[last] + last.length })
        insertBlock(editor, section({ type: 'paragraph' }))

        expect(editor.getJSON().content!.map(outline).join(' ')).toBe(expected)
        expect(() => editor.state.doc.check()).not.toThrow()
        editor.destroy()
    })
})
