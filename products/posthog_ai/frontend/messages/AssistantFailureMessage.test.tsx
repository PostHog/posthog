import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { AssistantFailureMessage } from './AssistantFailureMessage'

// Render content verbatim instead of through the real marked/LemonMarkdown pipeline,
// which is slow to mount and rewrites the markdown (e.g. strips emphasis asterisks).
jest.mock('./MarkdownMessage', () => ({
    MarkdownMessage: ({ content }: { content: string }) => <div data-attr="markdown">{content}</div>,
}))

describe('AssistantFailureMessage', () => {
    afterEach(cleanup)

    it('renders the supplied failure message', () => {
        render(<AssistantFailureMessage id="failure-1" content="Internal error: Failed to authenticate" />)

        expect(screen.getByText('Internal error: Failed to authenticate')).toBeInTheDocument()
    })

    it('falls back when no failure message is supplied', () => {
        render(<AssistantFailureMessage id="failure-1" content={null} />)

        expect(screen.getByText('*PostHog AI has failed to generate an answer. Please try again.*')).toBeInTheDocument()
    })

    it('renders an optional action', () => {
        render(<AssistantFailureMessage id="failure-1" content="Failed" action={<button>Try again</button>} />)

        expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    })
})
