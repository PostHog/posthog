import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsGroupByCreate } from 'products/logs/frontend/generated/api'

import { logsViewerConfigLogic } from '../LogsViewer/config/logsViewerConfigLogic'
import { logsGroupByLogic } from './logsGroupByLogic'

jest.mock('lib/api')
jest.mock('products/logs/frontend/generated/api')

describe('logsGroupByLogic', () => {
    let logic: ReturnType<typeof logsGroupByLogic.build>
    let configLogic: ReturnType<typeof logsViewerConfigLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.clearAllMocks()
        ;(logsGroupByCreate as jest.Mock).mockResolvedValue({
            groups: [],
            total_groups: 0,
            total_logs: 0,
            truncated: false,
        })
        configLogic = logsViewerConfigLogic({ id: 'test' })
        configLogic.mount()
        logic = logsGroupByLogic({ id: 'test' })
        logic.mount()
    })

    it('queries with the ordered dimension list and not at all without dimensions', async () => {
        // Mounting with no dimensions picked must not fire the aggregation.
        await expectLogic(logic).toFinishAllListeners()
        expect(logsGroupByCreate).not.toHaveBeenCalled()

        configLogic.actions.setGroupBys([
            { key: 'service.name', source: 'resource' },
            { key: 'severity_level', source: 'column' },
        ])
        await expectLogic(logic).toFinishAllListeners()

        expect(logsGroupByCreate).toHaveBeenCalledTimes(1)
        const body = (logsGroupByCreate as jest.Mock).mock.calls[0][1]
        expect(body.query.groupBys).toEqual([
            { key: 'service.name', source: 'resource' },
            { key: 'severity_level', source: 'column' },
        ])
        expect(body.query.groupBy).toBeUndefined()
    })
})
