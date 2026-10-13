import { render } from '@testing-library/react'

import { MarkdownMessage } from './MarkdownMessage'

jest.mock('lib/lemon-ui/LemonMarkdown', () => ({
    LemonMarkdown: {
        Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
        Renderer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    },
}))

describe('MarkdownMessage', () => {
    it('renders an inline reference as a link carrying the agent label', () => {
        const { container } = render(
            <MarkdownMessage id="desktop-message" content='Read <report id="example-report">the report</report>.' />
        )
        expect(container.textContent).toBe('Read [the report](/inbox/example-report).')
    })

    it('renders a query block as a linked title over its SQL', () => {
        const { container } = render(
            <MarkdownMessage
                id="desktop-message"
                content='<hogql display="block" title="Daily signups">SELECT 1</hogql>'
            />
        )
        expect(container.textContent).toContain('[Daily signups](/sql?open_query=SELECT%201)')
        expect(container.textContent).toContain('SELECT 1')
    })

    it('leaves a tag inside inline code literal', () => {
        const { container } = render(
            <MarkdownMessage id="desktop-message" content='`<insight id="example">Funnel</insight>`' />
        )
        expect(container.textContent).toBe('`<insight id="example">Funnel</insight>`')
    })

    it('hides the tag body during streaming and links it once complete', () => {
        const { container, rerender } = render(
            <MarkdownMessage id="streamed-message" content='Read <insight id="example">the' />
        )
        expect(container.textContent).toBe('Read ')
        rerender(<MarkdownMessage id="streamed-message" content='Read <insight id="example">the funnel</insight>.' />)
        expect(container.textContent).toBe('Read [the funnel](/insights/example).')
    })
})
