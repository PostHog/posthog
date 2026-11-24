import { act, render } from '@testing-library/react'
import { Editor } from '@tiptap/core'

import { EmailEditorContext } from '../emailEditorContext'
import { buildEmailExtensions } from '../emailExtensions'
import { EmailBlockFields } from './EmailBlockFields'

const sides = (px: number): Record<string, number> => ({ top: px, right: px, bottom: px, left: px })

describe('EmailBlockFields', () => {
    it('shows one padding value for an evenly padded block selected after an uneven one', () => {
        const editor = new Editor({
            extensions: buildEmailExtensions(''),
            content: {
                type: 'doc',
                content: [{ ...sides(1), right: 2 }, sides(10)].map((padding) => ({
                    type: 'paragraph',
                    attrs: { emailStyle: { padding } },
                    content: [{ type: 'text', text: 'Hi' }],
                })),
            },
        })
        editor.commands.setTextSelection(2)
        const fields = (): JSX.Element => (
            <EmailEditorContext.Provider value={{ pickImage: () => {} } as any}>
                <EmailBlockFields editor={editor} />
            </EmailEditorContext.Provider>
        )
        const { container, rerender } = render(fields())
        expect(container.querySelector('[data-attr="email-editor-block-padding-top"]')).toBeTruthy()

        act(() => {
            editor.commands.setTextSelection(6)
        })
        rerender(fields())
        expect(container.querySelector<HTMLInputElement>('[data-attr="email-editor-block-padding"]')?.value).toBe('10')
        editor.destroy()
    })
})
