import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AUTO_REFRESH_INTERVAL_MS, pipelineLogic } from './pipelineLogic'

const PIPELINE_ID = '0199a1b2-c3d4-7e5f-a6b7-c8d9e0f1a2b3'

const PIPELINE = {
    id: PIPELINE_ID,
    name: 'Logs ingestion pipeline',
    description: '',
    enabled: true,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    config: {
        nodes: [
            {
                id: 'capture',
                name: 'Capture',
                kind: 'capture-rs',
                stats: [{ id: 'accept', label: 'logs/s', format: 'rate', metric_name: 'm', aggregation: 'rate' }],
            },
        ],
        edges: [],
        variables: [],
    },
}

const EVALUATION = { nodes: [], edges: [], alerts: [], date_from: '', date_to: '' }

describe('pipelineLogic', () => {
    let logic: ReturnType<typeof pipelineLogic.build>

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: { '/api/projects/:team_id/metrics_pipelines/:id/': PIPELINE },
            post: { '/api/projects/:team_id/metrics_pipelines/:id/evaluate/': EVALUATION },
        })
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
        logic?.unmount()
    })

    // The poll is registered through cache.disposables, whose add() takes a setup
    // function returning a cleanup. Passing the cleanup directly runs it as setup and
    // kills the interval on the spot, so the toggle reads as on while nothing ticks.
    it('keeps polling on an interval after mount', async () => {
        logic = pipelineLogic({ id: PIPELINE_ID })
        logic.mount()

        await expectLogic(logic, () => {
            jest.advanceTimersByTime(AUTO_REFRESH_INTERVAL_MS)
        }).toDispatchActions(['refreshTick'])

        await expectLogic(logic, () => {
            jest.advanceTimersByTime(AUTO_REFRESH_INTERVAL_MS)
        }).toDispatchActions(['refreshTick'])
    })

    // A tick that still evaluates with the switch off would keep querying ClickHouse
    // for a pipeline the user paused.
    it('does not re-evaluate on a tick once auto-refresh is switched off', async () => {
        logic = pipelineLogic({ id: PIPELINE_ID })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setAutoRefresh(false)
        }).toMatchValues({ autoRefreshEnabled: false })

        await expectLogic(logic, () => {
            logic.actions.refreshTick()
        }).toNotHaveDispatchedActions(['evaluate'])
    })
})
