import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { logsFilterVolumePreviewLogic } from './logsFilterVolumePreviewLogic'

const SPARKLINE_ROWS = [{ time: '2026-08-04T11:00:00Z', service: 'api', count: 3, bytes_uncompressed: 2048 }]

const nonEmptyGroup: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [{ key: 'service.name', type: 'log_resource_attribute', operator: 'exact', value: 'api' } as never],
}

describe('logsFilterVolumePreviewLogic', () => {
    let logic: ReturnType<typeof logsFilterVolumePreviewLogic.build>
    let sparklineCalls: number
    let rankBysSeen: (string | undefined)[]
    let dateFromsSeen: (string | null | undefined)[]
    let sparklineFails: boolean

    beforeEach(() => {
        sparklineCalls = 0
        rankBysSeen = []
        dateFromsSeen = []
        sparklineFails = false
        useMocks({
            post: {
                '/api/environments/:team_id/logs/sparkline/': async ({ request }) => {
                    sparklineCalls += 1
                    const body = (await request.clone().json()) as {
                        query?: { sparklineRankBy?: string; dateRange?: { date_from?: string | null } }
                    }
                    rankBysSeen.push(body?.query?.sparklineRankBy)
                    dateFromsSeen.push(body?.query?.dateRange?.date_from)
                    return sparklineFails ? [500, { detail: 'boom' }] : [200, SPARKLINE_ROWS]
                },
            },
        })
        initKeaTests()
        logic = logsFilterVolumePreviewLogic({ previewKey: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('does not query for an empty filter group', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPreviewRequest({ type: FilterLogicalOperator.And, values: [] }, 'count')
        }).toFinishAllListeners()

        expect(logic.values.filterPreview).toBeNull()
        expect(sparklineCalls).toEqual(0)
    })

    it('loads the preview for a non-empty filter group', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPreviewRequest(nonEmptyGroup, 'count')
        })
            .toDispatchActions(['loadFilterPreviewSuccess'])
            .toFinishAllListeners()

        expect(logic.values.filterPreview).toEqual(SPARKLINE_ROWS)
        expect(sparklineCalls).toEqual(1)
    })

    it('sends the rank metric so the backend collapses around the right top-N', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPreviewRequest(nonEmptyGroup, 'bytes')
        })
            .toDispatchActions(['loadFilterPreviewSuccess'])
            .toFinishAllListeners()

        expect(rankBysSeen).toEqual(['bytes'])
    })

    it('refetches when only the rank metric changes', async () => {
        // The filter is identical, but a bytes-ranked top-10 is a different set of services from a
        // count-ranked one, so the cached count-ranked response can't be reused.
        await expectLogic(logic, () => {
            logic.actions.setPreviewRequest(nonEmptyGroup, 'count')
        })
            .toDispatchActions(['loadFilterPreviewSuccess'])
            .toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setPreviewRequest(nonEmptyGroup, 'bytes')
        })
            .toDispatchActions(['loadFilterPreviewSuccess'])
            .toFinishAllListeners()

        expect(sparklineCalls).toEqual(2)
        expect(rankBysSeen).toEqual(['count', 'bytes'])
    })

    it('queries a 24h window by default and the requested lookback otherwise', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPreviewRequest(nonEmptyGroup, 'count')
        })
            .toDispatchActions(['loadFilterPreviewSuccess'])
            .toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setPreviewRequest(nonEmptyGroup, 'count', '1h')
        })
            .toDispatchActions(['loadFilterPreviewSuccess'])
            .toFinishAllListeners()

        // A lookback change alone must refetch: the 24h response can't stand in for the 1h window.
        expect(sparklineCalls).toEqual(2)
        expect(dateFromsSeen).toEqual(['-24h', '-1h'])
    })

    it('drops the previous result when a later filter fails to load', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPreviewRequest(nonEmptyGroup, 'count')
        })
            .toDispatchActions(['loadFilterPreviewSuccess'])
            .toFinishAllListeners()
        expect(logic.values.filterPreview).toEqual(SPARKLINE_ROWS)

        // Without clearing on failure, this stale value would be charted — and projected from —
        // as if it described the newly selected filter.
        sparklineFails = true
        await expectLogic(logic, () => {
            logic.actions.setPreviewRequest({ ...nonEmptyGroup, type: FilterLogicalOperator.Or }, 'count')
        })
            .toDispatchActions(['loadFilterPreviewFailure'])
            .toFinishAllListeners()

        expect(logic.values.filterPreview).toBeNull()
    })

    it('debounces rapid filter edits into a single request', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPreviewRequest(nonEmptyGroup, 'count')
            logic.actions.setPreviewRequest({ ...nonEmptyGroup, type: FilterLogicalOperator.Or }, 'count')
        })
            .toDispatchActions(['loadFilterPreviewSuccess'])
            .toFinishAllListeners()

        expect(sparklineCalls).toEqual(1)
    })
})
