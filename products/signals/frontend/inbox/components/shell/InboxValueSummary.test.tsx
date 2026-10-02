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
    merged_pr_count: 12,
    people_count: 5,
    participation_complete: true,
}

describe('InboxValueSummary', () => {
    let readSummary: jest.Mock

    beforeEach(() => {
        localStorage.clear()
        jest.clearAllMocks()
        readSummary = jest.fn(() => [200, complete])
        useMocks({ get: { '/api/projects/:team_id/signals/inbox-summary/': readSummary } })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SIGNALS_INBOX_VALUE_SUMMARY]: true })
    })

    afterEach(cleanup)

    it('shows counts and records one view, then hides on dismissal', async () => {
        const { rerender } = render(<InboxValueSummary visible />)
        expect(await screen.findByText('12')).toBeInTheDocument()
        expect(screen.getByText('5')).toBeInTheDocument()
        expect(screen.getByText('Entire project')).toBeInTheDocument()
        expect(captureInboxValueSummary).toHaveBeenCalledWith('viewed', complete)
        rerender(<InboxValueSummary visible />)
        expect(captureInboxValueSummary).toHaveBeenCalledTimes(1)
        await userEvent.click(screen.getByRole('button', { name: 'Hide summary for 7 days' }))
        expect(screen.queryByRole('region', { name: 'Self-driving summary' })).not.toBeInTheDocument()
        expect(captureInboxValueSummary).toHaveBeenLastCalledWith('dismissed', complete)
    })

    it('does not mount or fetch with the flag disabled', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        render(<InboxValueSummary visible />)
        expect(readSummary).not.toHaveBeenCalled()
        expect(screen.queryByText('Self-driving in the last 7 days')).not.toBeInTheDocument()
    })

    it('hides zero merges without a view event', async () => {
        readSummary.mockReturnValue([200, { ...complete, merged_pr_count: 0, people_count: 0 }])
        render(<InboxValueSummary visible />)
        await waitFor(() => expect(readSummary).toHaveBeenCalled())
        expect(screen.queryByRole('region', { name: 'Self-driving summary' })).not.toBeInTheDocument()
        expect(captureInboxValueSummary).not.toHaveBeenCalled()
    })

    it('keeps the merge count when participation is incomplete', async () => {
        readSummary.mockReturnValue([200, { ...complete, people_count: null, participation_complete: false }])
        render(<InboxValueSummary visible />)
        expect(await screen.findByText('People count is updating')).toBeInTheDocument()
        expect(screen.getByText('12')).toBeInTheDocument()
        expect(screen.queryByText('0')).not.toBeInTheDocument()
    })

    it('does not record a hidden panel as viewed', async () => {
        const { rerender } = render(<InboxValueSummary visible={false} />)
        expect(readSummary).not.toHaveBeenCalled()
        expect(captureInboxValueSummary).not.toHaveBeenCalled()
        rerender(<InboxValueSummary visible />)
        expect(await screen.findByText('12')).toBeInTheDocument()
        expect(captureInboxValueSummary).toHaveBeenCalledTimes(1)
    })

    it('offers an inline retry after failure', async () => {
        readSummary.mockReturnValue([503, {}])
        render(<InboxValueSummary visible />)
        expect(await screen.findByText('Summary is not available.')).toBeInTheDocument()
        expect(captureInboxValueSummary).not.toHaveBeenCalled()
        readSummary.mockReturnValue([200, complete])
        await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
        expect(await screen.findByText('12')).toBeInTheDocument()
    })
})
