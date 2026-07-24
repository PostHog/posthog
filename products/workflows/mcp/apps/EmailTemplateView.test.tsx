import { cleanup, render, screen } from '@testing-library/react'
import { cloneElement, type ReactElement } from 'react'

import { type EmailTemplateData, EmailTemplateView } from './EmailTemplateView'

// quill is a workspace package that isn't transformed under the frontend jest harness — stub it
// so this stays a unit test of EmailTemplateView's own logic (preview iframe + conditional rendering).
jest.mock(
    '@posthog/quill',
    () => ({
        Card: ({ children }: { children: ReactElement }) => <div>{children}</div>,
        CardContent: ({ children }: { children: ReactElement }) => <div>{children}</div>,
        Badge: ({ children }: { children: ReactElement }) => <span>{children}</span>,
        Button: ({ children, render }: { children: ReactElement; render?: ReactElement }) =>
            render ? cloneElement(render, {}, children) : <button>{children}</button>,
    }),
    { virtual: true }
)

const baseTemplate: EmailTemplateData = {
    id: 'abc-123',
    name: 'Welcome email',
    type: 'email',
    content: {
        templating: 'liquid',
        email: {
            subject: 'Welcome to PostHog!',
            text: 'Hi there',
            html: '<html><body><h1>Hi {{ person.properties.name }}</h1></body></html>',
        },
    },
    _posthogUrl: 'https://app.posthog.com/project/1/workflows/library/templates/abc-123',
}

describe('EmailTemplateView', () => {
    afterEach(cleanup)

    it('renders the subject and the email html in a script-disabled sandboxed iframe', () => {
        const { container } = render(<EmailTemplateView template={baseTemplate} />)

        expect(screen.getByText('Welcome to PostHog!')).toBeTruthy()

        const iframe = container.querySelector('iframe')
        expect(iframe).not.toBeNull()
        expect(iframe!.getAttribute('srcdoc')).toBe(baseTemplate.content!.email!.html)
        // AI-generated html must not be able to run scripts.
        expect(iframe!.getAttribute('sandbox') ?? '').not.toContain('allow-scripts')
    })

    it('links the edit button to the _posthogUrl', () => {
        render(<EmailTemplateView template={baseTemplate} />)

        const link = screen.getByText(/open in editor/i).closest('a')
        expect(link?.getAttribute('href')).toBe(baseTemplate._posthogUrl)
    })

    it('omits the edit link when there is no _posthogUrl', () => {
        const { _posthogUrl, ...withoutUrl } = baseTemplate
        render(<EmailTemplateView template={withoutUrl} />)

        expect(screen.queryByText(/open in editor/i)).toBeNull()
    })

    it('falls back to plain text when there is no html', () => {
        const noHtml: EmailTemplateData = {
            ...baseTemplate,
            content: { templating: 'liquid', email: { subject: 'Welcome to PostHog!', text: 'Plain body only' } },
        }
        const { container } = render(<EmailTemplateView template={noHtml} />)

        expect(container.querySelector('iframe')).toBeNull()
        expect(screen.getByText('Plain body only')).toBeTruthy()
    })
})
