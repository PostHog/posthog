import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY, issueFiltersLogic } from '../IssueFilters/issueFiltersLogic'
import { BREAKDOWN_PRESETS } from './consts'
import { miniBreakdownsLogic } from './miniBreakdownsLogic'

describe('miniBreakdownsLogic', () => {
    let filters: ReturnType<typeof issueFiltersLogic.build>
    let breakdowns: ReturnType<typeof miniBreakdownsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: [] },
            },
        })
        initKeaTests()
        jest.spyOn(api, 'query').mockResolvedValue({ results: {} } as any)
        filters = issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY })
        filters.mount()
        breakdowns = miniBreakdownsLogic({ issueId: 'issue-id' })
        breakdowns.mount()
    })

    afterEach(() => {
        breakdowns.unmount()
        filters.unmount()
        jest.restoreAllMocks()
    })

    it('adds custom properties to the breakdown query and allows removing them', async () => {
        await expectLogic(breakdowns).toFinishAllListeners()

        await expectLogic(breakdowns, () => {
            breakdowns.actions.addBreakdownProperty('$current_url')
        })
            .toDispatchActions(['addBreakdownProperty', 'loadResponse', 'loadResponseSuccess'])
            .toFinishAllListeners()

        expect(breakdowns.values.breakdownProperties).toEqual([
            ...BREAKDOWN_PRESETS,
            { property: '$current_url', title: 'Current URL', removable: true },
        ])
        const latestQueryCall = jest.mocked(api.query).mock.calls.at(-1)
        expect(latestQueryCall).not.toBeUndefined()
        const latestBreakdownQuery = latestQueryCall?.[0] as any
        expect(latestBreakdownQuery.breakdownProperties).toEqual([
            ...BREAKDOWN_PRESETS.map(({ property }) => property),
            '$current_url',
        ])

        await expectLogic(breakdowns, () => {
            breakdowns.actions.removeBreakdownProperty('$current_url')
        }).toFinishAllListeners()

        expect(breakdowns.values.breakdownProperties).toEqual(BREAKDOWN_PRESETS)
    })
})
