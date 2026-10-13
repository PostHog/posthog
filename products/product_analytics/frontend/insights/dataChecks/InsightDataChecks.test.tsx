import { cleanup, render, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { InsightShortId } from '~/types'

import { InsightDataChecks } from './InsightDataChecks'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import { InsightDataChecksState } from './InsightDataChecksState'

const props = { dashboardItemId: '123' as InsightShortId }

describe('InsightDataChecks', () => {
    it('keeps its result while the page hides it, and lets go of it when the page goes', async () => {
        const dataChecks = jest.fn(() => [200, { status: 'passed', checks: [], events_checked: 10, sample_rate: 1 }])
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend': [],
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
            post: {
                '/api/environments/:team_id/query/:kind': { results: [] },
                '/api/projects/:team_id/insights/data_checks/': dataChecks,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INSIGHT_DATA_CHECKS], {
            [FEATURE_FLAGS.INSIGHT_DATA_CHECKS]: true,
        })

        render(<InsightDataChecksState insightProps={props} />)
        const mark = render(<InsightDataChecks insightProps={props} />)
        await waitFor(() => expect(dataChecks).toHaveBeenCalledTimes(1))
        mark.unmount()
        render(<InsightDataChecks insightProps={props} />)
        await expectLogic(insightDataChecksLogic(props)).toFinishAllListeners()

        expect(dataChecks).toHaveBeenCalledTimes(1)

        cleanup()

        expect(insightDataChecksLogic.findMounted(props)).toBeNull()
        expect(insightVizDataLogic.findMounted(props)).toBeNull()
    })
})
