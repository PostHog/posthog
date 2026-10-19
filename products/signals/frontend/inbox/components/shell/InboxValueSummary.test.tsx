/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper. */
import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { captureInboxValueSummary } from '../../inboxAnalytics'
import { InboxValueSummary } from './InboxValueSummary'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxValueSummary: jest.fn(),
}))

const complete = {
    period_start: '2026-09-13T12:00:00Z',
    period_end: '2026-09-20T12:00:00Z',
    merged_pr_count: 2,
    people_count: 2,
    participation_complete: true,
    pull_requests: [
        { repository: 'example/app', number: 42, url: 'https://github.com/example/app/pull/42' },
        { repository: 'example/sdk', number: 7, url: 'https://github.com/example/sdk/pull/7' },
    ],
    people: [
        { id: 10, login: 'example-merger' },
        { id: 20, login: 'example-reviewer' },
    ],
}

describe('InboxValueSummary', () => {
    let readSummary: jest.Mock

    beforeEach(() => {
        localStorage.clear()
        jest.clearAllMocks()
        readSummary = jest.fn(() => [200, complete])
        useMocks({ get: { '/api/projects/:team_id/signals/inbox_summary/': readSummary } })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SIGNALS_INBOX_VALUE_SUMMARY]: true })
    })

    afterEach(cleanup)

    it('shows counts and records one view, then hides on dismissal', async () => {
        const { rerender } = render(<InboxValueSummary visible />)
        expect(await screen.findByText('2 PRs')).toBeInTheDocument()
        expect(screen.getByText('2 people')).toBeInTheDocument()
        expect(screen.getByText('Self-driving activity')).toBeInTheDocument()
        expect(captureInboxValueSummary).toHaveBeenCalledWith('viewed', complete)
        rerender(<InboxValueSummary visible />)
        expect(captureInboxValueSummary).toHaveBeenCalledTimes(1)
        await userEvent.click(screen.getByLabelText('Hide summary for 7 days'))
        expect(screen.queryByLabelText('Self-driving summary')).not.toBeInTheDocument()
        expect(captureInboxValueSummary).toHaveBeenLastCalledWith('dismissed', complete)
    })

    it('shows linked pull requests and people from the summary', async () => {
        render(<InboxValueSummary visible />)
        await userEvent.hover(await screen.findByText('2 PRs'))
        const pullRequest = await screen.findByText('example/app#42')
        expect(pullRequest.closest('a')).toHaveAttribute('href', 'https://github.com/example/app/pull/42')
        await userEvent.unhover(screen.getByText('2 PRs'))
        await userEvent.hover(screen.getByText('2 people'))
        expect(await screen.findByText('@example-merger')).toBeInTheDocument()
        expect(screen.getByText('@example-reviewer')).toBeInTheDocument()
    })

    it('does not mount or fetch with the flag disabled', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        render(<InboxValueSummary visible />)
        expect(readSummary).not.toHaveBeenCalled()
        expect(screen.queryByText('Self-driving in the last 7 days')).not.toBeInTheDocument()
    })

    it('hides zero merges without a view event', async () => {
        readSummary.mockReturnValue([
            200,
            { ...complete, merged_pr_count: 0, people_count: 0, pull_requests: [], people: [] },
        ])
        render(<InboxValueSummary visible />)
        await waitFor(() => expect(readSummary).toHaveBeenCalled())
        expect(screen.queryByLabelText('Self-driving summary')).not.toBeInTheDocument()
        expect(captureInboxValueSummary).not.toHaveBeenCalled()
    })

    it('keeps the merge count when participation is incomplete', async () => {
        readSummary.mockReturnValue([
            200,
            { ...complete, people_count: null, participation_complete: false, people: null },
        ])
        render(<InboxValueSummary visible />)
        expect(await screen.findByText('people count updating')).toBeInTheDocument()
        expect(screen.getByText('2 PRs')).toBeInTheDocument()
        expect(screen.queryByText('0')).not.toBeInTheDocument()
    })

    it('does not record a hidden panel as viewed', async () => {
        const { rerender } = render(<InboxValueSummary visible={false} />)
        expect(readSummary).not.toHaveBeenCalled()
        expect(captureInboxValueSummary).not.toHaveBeenCalled()
        rerender(<InboxValueSummary visible />)
        expect(await screen.findByText('2 PRs')).toBeInTheDocument()
        expect(captureInboxValueSummary).toHaveBeenCalledTimes(1)
    })

    it('offers an inline retry after failure', async () => {
        readSummary.mockReturnValue([503, {}])
        render(<InboxValueSummary visible />)
        expect(await screen.findByText('Summary is not available.')).toBeInTheDocument()
        expect(captureInboxValueSummary).not.toHaveBeenCalled()
        readSummary.mockReturnValue([200, complete])
        await userEvent.click(screen.getByText('Try again'))
        expect(await screen.findByText('2 PRs')).toBeInTheDocument()
    })
})
