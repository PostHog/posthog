import { render } from '@testing-library/react'

import { MarkdownMessage } from './MarkdownMessage'

jest.mock('lib/lemon-ui/LemonMarkdown', () => ({
    LemonMarkdown: {
        Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
        Renderer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    },
}))

describe('MarkdownMessage', () => {
    it.each([
        ['inline reference', 'Read <report id="example-report">the report</report>.', 'Read the report.'],
        ['query block', '<hogql display="block" title="Daily signups">SELECT 1</hogql>', 'Daily signups'],
        ['code example', '`<insight id="example">Funnel</insight>`', '`Funnel`'],
    ])('shows readable %s from a Desktop conversation', (_name, content, expected) => {
        const { container } = render(<MarkdownMessage id="desktop-message" content={content} />)
        expect(container.textContent).toBe(expected)
    })

    it('flattens a tag once the streamed content is complete', () => {
        const { container, rerender } = render(
            <MarkdownMessage id="streamed-message" content='Read <insight id="example">the' />
        )
        rerender(<MarkdownMessage id="streamed-message" content='Read <insight id="example">the funnel</insight>.' />)
        expect(container.textContent).toBe('Read the funnel.')
    })
})
