import { act, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ObservationSearchResultApi } from '../generated/api.schemas'
import { type ResultsView, observationSearchLogic } from './observationSearchLogic'
import { SearchResults } from './SearchResults'

describe('SearchResults', () => {
    const results = [
        {
            observation: { id: 'obs-1', session_id: 's-expired', created_at: '2026-01-01T00:00:00Z' },
            matched_content: 'User rage-clicked the coupon field',
            distance: 0.1,
        },
    ] as unknown as ObservationSearchResultApi[]

    // The availability check resolves after the first render, so a result goes from playable to expired
    // while mounted. Hooks that only run on one side of that branch crash the whole view.
    it.each<ResultsView>(['grid', 'list'])(
        'marks a result expired after it first rendered as playable in the %s view',
        async (view) => {
            let releaseRecordings: () => void = () => {}
            const recordingsReleased = new Promise<void>((resolve) => {
                releaseRecordings = resolve
            })
            useMocks({
                get: {
                    '/api/environments/:team_id/session_recordings': async () => {
                        await recordingsReleased
                        return [200, { results: [], has_next: false }]
                    },
                },
            })
            initKeaTests()
            router.actions.push(urls.replayVision(), { tab: 'search' })
            const logicProps = { teamId: 1, userId: 'user-1' }
            const logic = observationSearchLogic(logicProps)
            logic.mount()
            logic.actions.setView(view)

            const { container, unmount } = render(<SearchResults {...logicProps} />)
            act(() => logic.actions.searchSuccess(results, 'confused users', false))

            expect(container.querySelector('[data-attr="vision-search-result-watch"]')).not.toBeNull()
            expect(container.querySelector('[data-attr="vision-recording-expired-tag"]')).toBeNull()

            await act(async () => {
                releaseRecordings()
                await recordingsReleased
            })

            await waitFor(() =>
                expect(container.querySelector('[data-attr="vision-recording-expired-tag"]')).not.toBeNull()
            )
            expect(container.querySelector('[data-attr="vision-search-result-watch"]')).toBeNull()
            unmount()
            logic.unmount()
        }
    )
})
