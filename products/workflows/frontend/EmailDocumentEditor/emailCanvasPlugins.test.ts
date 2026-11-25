import { Editor, JSONContent } from '@tiptap/core'
import { AllSelection, NodeSelection } from '@tiptap/pm/state'

import { EmailBlockKeymap } from './emailCanvasPlugins'
import { buildEmailExtensions } from './emailExtensions'

describe('emailCanvasPlugins', () => {
    it.each<{ name: string; block: JSONContent; kept: boolean }>([
        { name: 'an HTML block', block: { type: 'emailHtml', attrs: { html: '<p>Whole email</p>' } }, kept: true },
        { name: 'a divider', block: { type: 'horizontalRule' }, kept: false },
    ])('typing on selected $name keeps it: $kept', ({ block, kept }) => {
        const editor = new Editor({
            extensions: [...buildEmailExtensions(''), EmailBlockKeymap],
            content: { type: 'doc', content: [block] },
        })
        editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc, 0)))

        editor.view.dom.dispatchEvent(new KeyboardEvent('keypress', { charCode: 97, bubbles: true, cancelable: true }))

        expect(editor.state.doc.firstChild?.type.name === block.type).toEqual(kept)
        editor.destroy()
    })

    it('selects the whole email only on the second select all from a selected block', () => {
        const editor = new Editor({
            extensions: [...buildEmailExtensions(''), EmailBlockKeymap],
            content: { type: 'doc', content: [{ type: 'paragraph' }, { type: 'emailSpacer' }] },
        })
        editor.commands.setNodeSelection(2)
        const selectAll = (): boolean =>
            editor.view.dom.dispatchEvent(
                new KeyboardEvent('keydown', { key: 'a', ctrlKey: true, bubbles: true, cancelable: true })
            )

        selectAll()
        expect(editor.state.selection).toBeInstanceOf(NodeSelection)
        selectAll()
        expect(editor.state.selection).toBeInstanceOf(AllSelection)
        editor.destroy()
    })
})
