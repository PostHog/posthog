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

    beforeEach(() => {
        sparklineCalls = 0
        useMocks({
            post: {
                '/api/environments/:team_id/logs/sparkline/': () => {
                    sparklineCalls += 1
                    return [200, SPARKLINE_ROWS]
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
            logic.actions.setFilterGroup({ type: FilterLogicalOperator.And, values: [] })
        }).toFinishAllListeners()

        expect(logic.values.filterPreview).toBeNull()
        expect(sparklineCalls).toEqual(0)
    })

    it('loads the preview for a non-empty filter group', async () => {
        await expectLogic(logic, () => {
            logic.actions.setFilterGroup(nonEmptyGroup)
        })
            .toDispatchActions(['loadFilterPreviewSuccess'])
            .toFinishAllListeners()

        expect(logic.values.filterPreview).toEqual(SPARKLINE_ROWS)
        expect(sparklineCalls).toEqual(1)
    })

    it('debounces rapid filter edits into a single request', async () => {
        await expectLogic(logic, () => {
            logic.actions.setFilterGroup(nonEmptyGroup)
            logic.actions.setFilterGroup({ ...nonEmptyGroup, type: FilterLogicalOperator.Or })
        })
            .toDispatchActions(['loadFilterPreviewSuccess'])
            .toFinishAllListeners()

        expect(sparklineCalls).toEqual(1)
    })
})
