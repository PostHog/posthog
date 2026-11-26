import { act, render } from '@testing-library/react'

import { EmailHtmlCodeField } from './EmailHtmlCodeField'

let mockEditorProps: any
jest.mock('lib/monaco/CodeEditor', () => ({
    CodeEditor: (props: any) => {
        mockEditorProps = props
        return null
    },
}))

describe('EmailHtmlCodeField', () => {
    it('applies each edit to the block it was typed for before the field can close or the block can move', () => {
        jest.useFakeTimers()
        const onChange = jest.fn()
        const { unmount } = render(<EmailHtmlCodeField html="<p>A</p>" onChange={onChange} />)

        act(() => mockEditorProps.onChange('<p>A!</p>'))
        expect(onChange).toHaveBeenCalledTimes(1)
        expect(onChange).toHaveBeenLastCalledWith('<p>A!</p>')

        unmount()
        act(() => jest.runAllTimers())
        expect(onChange).toHaveBeenCalledTimes(1)

        // Undo or the larger editor changes the block from outside, and the code shown follows it.
        const second = render(<EmailHtmlCodeField html="<p>A!</p>" onChange={onChange} />)
        second.rerender(<EmailHtmlCodeField html="<p>B</p>" onChange={onChange} />)
        expect(mockEditorProps.value).toBe('<p>B</p>')
        jest.useRealTimers()
    })
})
