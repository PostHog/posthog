import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { InboxTabBar } from './InboxTabBar'

describe('InboxTabBar', () => {
    beforeEach(() => {
        useMocks({
            get: {
                // The count chips and reviewer scope load on mount; keep them out of the way.
                '/api/projects/:team_id/signals/reports/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    // Guards the fix for the swallowed tab click: a tab link that drops the active filter params
    // lands on a bare inbox URL, and `inboxFiltersLogic` then races to rewrite the params back —
    // which could swallow the tab switch. The link must be a real anchor that carries the params.
    it('renders each tab as a link that keeps the active filter query params', () => {
        router.actions.push('/inbox/pulls', { scope: 'entire-project', priority: 'P1' })

        render(<InboxTabBar />)

        const reportsLink = screen.getByText('Reports').closest('a')
        expect(reportsLink).not.toBeNull()
        expect(reportsLink).toHaveAttribute('href', expect.stringContaining('/inbox/reports'))
        expect(reportsLink!.getAttribute('href')).toContain('scope=entire-project')
        expect(reportsLink!.getAttribute('href')).toContain('priority=P1')
    })
})
