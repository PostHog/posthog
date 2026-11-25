import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Editor, JSONContent } from '@tiptap/core'

import { buildEmailExtensions } from '../emailExtensions'
import { EmailColumnsFields } from './EmailColumnsFields'
import { EmailVisibilityFields } from './EmailVisibilityFields'
import { EmailColorField } from './fields/EmailColorField'

describe('email style fields', () => {
    let editor: Editor | undefined
    const originalCss = window.CSS

    afterEach(() => {
        cleanup()
        editor?.destroy()
        editor = undefined
        window.CSS = originalCss
    })

    function open(block: JSONContent): Editor {
        editor = new Editor({ extensions: buildEmailExtensions(''), content: { type: 'doc', content: [block] } })
        return editor
    }

    it.each([
        ['{% if  %}', ''],
        ['{% if a == 1 %}', 'a == 1'],
        ['{% if a  %}', 'a '],
        ['{%- if a -%}', 'a'],
        ['{%if a%}', 'a'],
    ])('reads the condition %j as %j and writes back what is typed', (before, shown) => {
        open({
            type: 'paragraph',
            attrs: { emailVisibility: { condition: { before, after: '{% endif %}' } } },
        })
        render(<EmailVisibilityFields editor={editor!} pos={0} />)
        const input = screen.getByLabelText<HTMLInputElement>('Only if')
        expect(input.value).toBe(shown)

        fireEvent.change(input, { target: { value: 'b ' } })
        expect(editor!.state.doc.firstChild?.attrs.emailVisibility.condition.before).toBe('{% if b  %}')
    })

    it("keeps the columns when the row's name is clicked", () => {
        const column = { type: 'emailColumn', content: [{ type: 'paragraph' }] }
        open({ type: 'emailColumns', content: [column, column, column] })
        render(<EmailColumnsFields editor={editor!} pos={0} columnIndex={0} />)

        fireEvent.click(screen.getByText('Number'))
        expect(editor!.state.doc.firstChild?.childCount).toBe(3)
    })

    it('shows the saved color again after text that is not a color', () => {
        const onChange = jest.fn()
        // jsdom has no CSS.supports.
        window.CSS = {
            supports: (property: string, value: string) =>
                value === 'inherit' || (property === 'color' && value === 'teal'),
        } as any
        render(<EmailColorField label="Background" value="#ffffff" onChange={onChange} />)
        const input = screen.getByLabelText<HTMLInputElement>('Background', { selector: 'input:not([type=color])' })

        fireEvent.change(input, { target: { value: '#zz' } })
        fireEvent.change(input, { target: { value: 'notacolor' } })
        fireEvent.change(input, { target: { value: 'inherit' } })
        fireEvent.blur(input)
        expect(onChange).not.toHaveBeenCalled()
        expect(input.value).toBe('#ffffff')

        fireEvent.change(input, { target: { value: 'teal' } })
        expect(onChange.mock.calls).toEqual([['teal']])
    })
})
