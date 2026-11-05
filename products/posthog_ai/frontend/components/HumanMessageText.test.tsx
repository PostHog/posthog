import { render } from '@testing-library/react'

import { HumanMessageText } from './HumanMessageText'

// Jest replaces `react-markdown` with a stub that prints its source, so these cases assert the
// markdown handed to the renderer. The real renderer drops unescaped raw HTML (`skipHtml`).
describe('HumanMessageText', () => {
    it.each([
        [
            'an unknown tag',
            'Repeat this back exactly: keep <example> intact',
            'Repeat this back exactly: keep \\<example> intact',
        ],
        ['a closing tag', 'keep </example> intact', 'keep \\</example> intact'],
        ['a tag with attributes', 'keep <widget size="large"> intact', 'keep \\<widget size="large"> intact'],
        ['a tag in inline code', 'keep `<example>` intact', 'keep `<example>` intact'],
        ['a url autolink', 'see <https://example.com>', 'see <https://example.com>'],
        [
            'an object tag, which becomes a link',
            'See <insight id="abc">the funnel</insight>',
            'See [the funnel](/insights/abc)',
        ],
    ])('sends %s to the markdown renderer in a form that shows it', (_, text, expected) => {
        const { container } = render(<HumanMessageText text={text} id="human-message" />)
        expect(container.textContent).toBe(expected)
    })
})
