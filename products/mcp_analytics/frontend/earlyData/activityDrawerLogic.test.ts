import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { EventType } from '~/types'

import { ActivityDrawerRow, activityDrawerLogic } from './activityDrawerLogic'

jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { capture: jest.fn() } }))

const TIMESTAMP = '2026-11-18T10:00:00.000Z'

const toolCallEvent = (uuid: string): EventType => ({
    id: uuid,
    uuid,
    distinct_id: 'user',
    event: '$mcp_tool_call',
    timestamp: TIMESTAMP,
    properties: {},
    elements: [],
})

const row = (eventId: string, sessionId: string, event?: EventType): ActivityDrawerRow => ({
    eventId,
    sessionId,
    timestamp: TIMESTAMP,
    event,
})

describe('activityDrawerLogic', () => {
    let logic: ReturnType<typeof activityDrawerLogic.build>
    let queryMock: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        router.actions.push(urls.mcpAnalyticsActivity(), { date_from: '-7d' })
        queryMock = jest.spyOn(api, 'query').mockResolvedValue({ results: [[toolCallEvent('a')]] } as any)
        logic = activityDrawerLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('steps through the loaded rows on the events they carry, without looking any up', async () => {
        const rows = ['a', 'b', 'c'].map((eventId) => row(eventId, 'ses_1', toolCallEvent(eventId)))
        logic.actions.setRows(rows)

        await expectLogic(logic, () => logic.actions.openRow(rows[0], 'list')).toFinishAllListeners()
        expect(logic.values.previousRow).toBeNull()

        await expectLogic(logic, () => logic.actions.stepTo('next')).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.stepTo('next')).toFinishAllListeners()
        expect(logic.values.openedRow?.eventId).toBe('c')
        expect(logic.values.position).toEqual({ index: 2, total: 3 })
        expect(logic.values.nextRow).toBeNull()
        expect(logic.values.event?.uuid).toBe('c')
        expect(queryMock).not.toHaveBeenCalled()
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
        expect(logic.values.event?.uuid).toBe('a')

        await expectLogic(logic, () => logic.actions.close()).toFinishAllListeners()
        expect(router.values.searchParams).toEqual({ date_from: '-7d' })
    })
})
