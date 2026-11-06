import { Editor } from '@tiptap/core'

import { createEmailEditorAdapter } from './emailEditorAdapter'
import { buildEmailExtensions } from './emailExtensions'

jest.mock('./components/EmailHtmlBlockView', () => ({ EmailHtmlBlockView: () => null }))
jest.mock('./components/EmailImageBlockView', () => ({ EmailImageBlockView: () => null }))
jest.mock('./components/EmailVariableChip', () => ({ EmailVariableChip: () => null }))

describe('emailEditorAdapter', () => {
    it('keeps the page style when a saved document loads into an open editor', () => {
        const editor = new Editor({ extensions: buildEmailExtensions('') })
        const adapter = createEmailEditorAdapter(editor)
        const doc = {
            type: 'doc',
            attrs: { page: { bodyWidth: 560 } },
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }],
        }

        adapter.loadDocument(doc)

        expect(editor.getJSON().attrs?.page).toEqual({ bodyWidth: 560 })
        expect(editor.getText()).toEqual('Hello')
        editor.destroy()
    })
})
