import { render } from '@testing-library/react'

import { HumanMessageText } from './HumanMessageText'

// Jest replaces `react-markdown` with a stub that prints its source, so these cases assert the
// markdown handed to the renderer. The renderer shows raw HTML as text (`literalHtml`).
describe('HumanMessageText', () => {
    it.each([
        ['an unknown tag', 'keep <example> intact', 'keep <example> intact'],
        ['a trailing partial tag', 'keep <insight', 'keep <insight'],
        [
            'an object tag, which becomes a link',
            'See <insight id="abc">the funnel</insight>',
            'See [the funnel](/insights/abc)',
        ],
    ])('sends %s to the markdown renderer', (_, text, expected) => {
        const { container } = render(<HumanMessageText text={text} id="human-message" />)
        expect(container.textContent).toBe(expected)
    })
})
