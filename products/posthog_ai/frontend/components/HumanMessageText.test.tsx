import { render } from '@testing-library/react'

import { HumanMessageText } from './HumanMessageText'

// Jest replaces `react-markdown` with a stub that prints its source, so this asserts the markdown
// handed to the renderer.
describe('HumanMessageText', () => {
    it('keeps a trailing partial tag, because a sent message is complete', () => {
        const { container } = render(<HumanMessageText text="keep <insight" id="human-message" />)
        expect(container.textContent).toBe('keep <insight')
    })
})
