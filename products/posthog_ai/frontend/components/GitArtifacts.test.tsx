import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { PullRequestCard } from './PullRequestCard'
import { RunContext } from './RunContext'

const PR_URL = 'https://github.com/PostHog/posthog/pull/123'

// Visibility is the caller's concern (ThreadView mounts these only when the run reports the
// relevant artifact), so these cover only that each renders its data when mounted.
describe('sandbox git artifacts', () => {
    afterEach(() => {
        cleanup()
    })

    it('RunContext renders the working and base branch', () => {
        render(<RunContext branch="feat/x" baseBranch="master" repo="PostHog/posthog" />)
        expect(screen.getByText('feat/x')).toBeInTheDocument()
        expect(screen.getByText('master')).toBeInTheDocument()
        expect(screen.getByText('PostHog/posthog')).toBeInTheDocument()
    })

    it('RunContext renders just the branch when there is no base or repo', () => {
        render(<RunContext branch="feat/x" />)
        expect(screen.getByText('feat/x')).toBeInTheDocument()
    })

    it('PullRequestCard renders the success card and a link to the PR', () => {
        render(<PullRequestCard prUrl={PR_URL} branch="feat/x" />)
        expect(screen.getByText('Pull request opened')).toBeInTheDocument()
        expect(screen.getByText('feat/x')).toBeInTheDocument()
        expect(screen.getByText(/Open on GitHub/).closest('a')).toHaveAttribute('href', PR_URL)
    })
})
