import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { AssistantFailureMessage } from './AssistantFailureMessage'

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

        expect(screen.getByText('Try again')).toBeInTheDocument()
    })
})
