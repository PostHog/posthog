import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'

import { ThreadSkinContext } from '../components/quill/quillThreadContext'
import { AssistantFailureMessage } from './AssistantFailureMessage'

// The failure bubble has a skin per thread, and both must keep the message and the action visible.
describe.each([
    ['lemon', (ui: ReactElement) => ui],
    ['quill', (ui: ReactElement) => <ThreadSkinContext.Provider value="quill">{ui}</ThreadSkinContext.Provider>],
])('AssistantFailureMessage (%s)', (_skin, wrap) => {
    afterEach(cleanup)

    it('renders the supplied failure message', () => {
        render(wrap(<AssistantFailureMessage id="failure-1" content="Internal error: Failed to authenticate" />))

        expect(screen.getByText('Internal error: Failed to authenticate')).toBeInTheDocument()
    })

    it('falls back when no failure message is supplied', () => {
        render(wrap(<AssistantFailureMessage id="failure-1" content={null} />))

        expect(screen.getByText('*PostHog AI has failed to generate an answer. Please try again.*')).toBeInTheDocument()
    })

    it('renders an optional action', () => {
        render(wrap(<AssistantFailureMessage id="failure-1" content="Failed" action={<button>Try again</button>} />))

        expect(screen.getByText('Try again')).toBeInTheDocument()
    })
})
