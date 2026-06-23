import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { SandboxPullRequestCard } from './SandboxPullRequestCard'
import { SandboxRunContext } from './SandboxRunContext'

const PR_URL = 'https://github.com/PostHog/posthog/pull/123'

// Visibility is the caller's concern (SandboxThread mounts these only when the run reports the
// relevant artifact), so these cover only that each renders its data when mounted.
describe('sandbox git artifacts', () => {
    afterEach(() => {
        cleanup()
    })

    it('SandboxRunContext renders the working and base branch', () => {
        render(<SandboxRunContext branch="feat/x" baseBranch="master" repo="PostHog/posthog" />)
        expect(screen.getByText('feat/x')).toBeInTheDocument()
        expect(screen.getByText('master')).toBeInTheDocument()
        expect(screen.getByText('PostHog/posthog')).toBeInTheDocument()
    })

    it('SandboxRunContext renders just the branch when there is no base or repo', () => {
        render(<SandboxRunContext branch="feat/x" />)
        expect(screen.getByText('feat/x')).toBeInTheDocument()
    })

    it('SandboxPullRequestCard renders the success card and a link to the PR', () => {
        render(<SandboxPullRequestCard prUrl={PR_URL} branch="feat/x" />)
        expect(screen.getByText('Pull request opened')).toBeInTheDocument()
        expect(screen.getByText('feat/x')).toBeInTheDocument()
        expect(screen.getByRole('link', { name: /Open on GitHub/ })).toHaveAttribute('href', PR_URL)
    })
})
