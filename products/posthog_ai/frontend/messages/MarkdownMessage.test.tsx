import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { MarkdownMessage } from './MarkdownMessage'

describe('MarkdownMessage', () => {
    afterEach(cleanup)

    it('renders without crashing when content is undefined', () => {
        // Streaming call sites can pass undefined before the first chunk arrives. This used to throw
        // "Cannot read properties of undefined (reading 'replace')" in parseMarkdownIntoBlocks and
        // take down the whole thread render.
        expect(() => render(<MarkdownMessage id="msg-1" content={undefined} />)).not.toThrow()
    })
})
