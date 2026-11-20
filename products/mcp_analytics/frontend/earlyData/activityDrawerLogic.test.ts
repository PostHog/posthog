import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsSessionsList, mcpAnalyticsSessionsToolCalls } from '../generated/api'
import { ActivityDrawerRow, activityDrawerLogic } from './activityDrawerLogic'

jest.mock('../generated/api', () => ({
    mcpAnalyticsSessionsList: jest.fn(),
    mcpAnalyticsSessionsToolCalls: jest.fn(),
    mcpAnalyticsSessionsGenerateIntent: jest.fn(),
}))
jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { capture: jest.fn() } }))

const listMock = mcpAnalyticsSessionsList as jest.Mock
const toolCallsMock = mcpAnalyticsSessionsToolCalls as jest.Mock

const TIMESTAMP = '2026-11-18T10:00:00.000Z'

const row = (eventId: string, sessionId: string): ActivityDrawerRow => ({ eventId, sessionId, timestamp: TIMESTAMP })

describe('activityDrawerLogic', () => {
    let logic: ReturnType<typeof activityDrawerLogic.build>

    beforeEach(() => {
        initKeaTests()
        router.actions.push(urls.mcpAnalyticsActivity(), { date_from: '-7d' })
        listMock.mockImplementation(async (_projectId: string, { search }: { search: string }) => ({
            results: [{ session_id: search, session_start: TIMESTAMP, session_end: TIMESTAMP, tool_calls: 1 }],
            has_next: false,
        }))
        toolCallsMock.mockResolvedValue({ results: [], has_next: false })
        logic = activityDrawerLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    it('steps through the loaded rows, loading a session only when the step leaves the open one', async () => {
        logic.actions.setRows([row('a', 'ses_1'), row('b', 'ses_1'), row('c', 'ses_2')])

        await expectLogic(logic, () => logic.actions.openRow(row('a', 'ses_1'), 'list')).toFinishAllListeners()
        expect(logic.values.previousRow).toBeNull()

        await expectLogic(logic, () => logic.actions.stepTo('next')).toFinishAllListeners()
        expect(listMock).toHaveBeenCalledTimes(1)

        await expectLogic(logic, () => logic.actions.stepTo('next')).toFinishAllListeners()
        expect(logic.values.openedRow?.eventId).toBe('c')
        expect(logic.values.position).toEqual({ index: 2, total: 3 })
        expect(logic.values.nextRow).toBeNull()
        expect(logic.values.session?.session_id).toBe('ses_2')
        expect(listMock).toHaveBeenCalledTimes(2)
    })

    it('opens from a shared link and leaves the other params when it closes', async () => {
        router.actions.push(urls.mcpAnalyticsActivity(), {
            date_from: '-7d',
            session: 'ses_1',
            call: 'a',
            ts: TIMESTAMP,
        })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.openedRow).toEqual(row('a', 'ses_1'))
        expect(logic.values.session?.session_id).toBe('ses_1')

        await expectLogic(logic, () => logic.actions.close()).toFinishAllListeners()
        expect(router.values.searchParams).toEqual({ date_from: '-7d' })
    })
})
