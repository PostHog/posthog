import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { Editor } from '@tiptap/core'

import { buildEmailExtensions } from '../emailExtensions'
import { EmailBlockFields } from './EmailBlockFields'

const sides = (px: number): Record<string, number> => ({ top: px, right: px, bottom: px, left: px })

describe('EmailBlockFields', () => {
    let editor: Editor

    function block(padding: Record<string, number>): Record<string, any> {
        return { type: 'paragraph', attrs: { emailStyle: { padding } }, content: [{ type: 'text', text: 'Hi' }] }
    }

    afterEach(() => {
        cleanup()
        editor.destroy()
    })

    it.each([
        ['opened with the icon, after selecting another block', sides(5), () => editor.commands.setTextSelection(6)],
        [
            'opened for an uneven block, after deleting it',
            { ...sides(1), right: 2 },
            () => editor.chain().deleteRange({ from: 0, to: 4 }).setTextSelection(2).run(),
        ],
    ])('closes the four sides %s', (_, firstPadding, moveOn) => {
        editor = new Editor({
            extensions: buildEmailExtensions(''),
            content: { type: 'doc', content: [block(firstPadding), block(sides(10))] },
        })
        editor.commands.setTextSelection(2)
        const { container, rerender } = render(<EmailBlockFields editor={editor} />)
        const find = (attr: string): HTMLInputElement | null => container.querySelector(`[data-attr="${attr}"]`)
        if (find('email-editor-block-padding')) {
            fireEvent.click(find('email-editor-block-padding-each')!)
        }
        expect(find('email-editor-block-padding-top')).toBeTruthy()

        act(() => {
            moveOn()
        })
        rerender(<EmailBlockFields editor={editor} />)
        expect(find('email-editor-block-padding')?.value).toBe('10')
    })
})
