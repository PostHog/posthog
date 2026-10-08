import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mockScoutSuggestionSet, mockScoutSuggestions } from '../../../__mocks__/scoutConfigs'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { ScoutSuggestionsStrip } from './ScoutSuggestionsStrip'

describe('ScoutSuggestionsStrip', () => {
    afterEach(cleanup)

    function useSetupMocks(items: typeof mockScoutSuggestions): void {
        useMocks({
            get: {
                '/api/projects/:team/signals/scout/configs/': [],
                '/api/projects/:team/signals/scout/suggestions/': mockScoutSuggestionSet({ items }),
            },
            post: {
                '/api/projects/:team/signals/scout/suggestions/refresh/': [200, { workflow_id: 'workflow-1' }],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SCOUTS_SUGGESTIONS_UI], {
            [FEATURE_FLAGS.SCOUTS_SUGGESTIONS_UI]: true,
        })
    }

    // The strip opens collapsed, so a press from the collapsed line is the common path for Refresh,
    // not an edge case.
    it('shows how the scan is going when Refresh is pressed from the collapsed line', async () => {
        useSetupMocks(mockScoutSuggestions)
        const { findByText, getByText } = render(<ScoutSuggestionsStrip />)
        await findByText(/Watch signup drop-off by plan/)

        fireEvent.click(getByText('Refresh'))

        expect(await findByText(/less than a minute so far/)).toBeTruthy()
        expect(getByText(/You can leave this page/)).toBeTruthy()
        expect(getByText(/Watch signup drop-off by plan/)).toBeTruthy()
    })

    it('still says a scan is running when there are no picks left to name', async () => {
        useSetupMocks([])
        const logic = scoutSuggestionsLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.suggestionSet).not.toBeNull())

        const { findByText } = render(<ScoutSuggestionsStrip />)
        act(() => logic.actions.requestRefresh('strip'))

        expect(await findByText(/Scanning the project for new picks/)).toBeTruthy()
        logic.unmount()
    })
})
