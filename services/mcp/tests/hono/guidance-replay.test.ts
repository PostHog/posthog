import { describe, expect, it, vi } from 'vitest'

import { MCP_GUIDANCE_EMPTY_STATES_FLAG } from '@/hono/guidance/empty-result-rule'
import { GuidanceEngine, type GuidanceCall } from '@/hono/guidance/engine'

import { makeToolExecutorState } from '../shared/test-utils'
import { makeGuidanceRedis } from './helpers/guidance-redis-stubs'

const RECORDING_ON = { ingested_event: true, session_recording_opt_in: true }
const RECORDING_OFF = { ingested_event: true, session_recording_opt_in: false }

async function noticeFor(project: unknown, args: Record<string, unknown>): Promise<string | undefined> {
    const state = makeToolExecutorState(
        [{ name: 'query-session-recordings-list' }, { name: 'read-data-schema' }, { name: 'execute-sql' }],
        { suppressAnalytics: false, toolFeatureFlags: { [MCP_GUIDANCE_EMPTY_STATES_FLAG]: true } }
    )
    state.context.stateManager = { getCachedOrFetchProject: vi.fn(async () => project) } as any
    const call: GuidanceCall = { toolName: 'query-session-recordings-list', args, isError: false, resultEmpty: true }
    return (await new GuidanceEngine(makeGuidanceRedis()).evaluate(state, call))?.ruleId
}

describe('replay empty-result guidance', () => {
    it.each([
        ['recording off', RECORDING_OFF, { session_ids: ['a'], properties: [{ key: 'x' }] }, 'recording-off'],
        ['session IDs with the default range', RECORDING_ON, { session_ids: ['a'] }, undefined],
        ['session IDs with a date range', RECORDING_ON, { session_ids: ['a'], date_from: '-30d' }, 'session-missing'],
        ['a person', RECORDING_ON, { person_uuid: 'p', date_from: '-7d' }, 'person'],
        ['property filters', RECORDING_ON, { properties: [{ key: 'x' }], date_from: '-7d' }, 'filters'],
        ['no filters and an empty filter list', RECORDING_ON, { properties: [], limit: 10 }, 'range'],
        ['an empty session ID list', RECORDING_ON, { session_ids: [] }, undefined],
        [
            'session IDs with a property filter',
            RECORDING_ON,
            { session_ids: ['a'], properties: [{ key: 'x' }] },
            'filters',
        ],
        [
            'a person with the test account filter',
            RECORDING_ON,
            { person_uuid: 'p', filter_test_accounts: true },
            'filters',
        ],
        ['a later page', RECORDING_ON, { after: 'cursor' }, undefined],
        ['a project with no data', { ...RECORDING_OFF, ingested_event: false }, {}, undefined],
        ['an unknown recording setting', { ingested_event: true }, {}, undefined],
    ])('handles %s', async (_label, project, args, expected) => {
        expect(await noticeFor(project, args)).toBe(expected && `replay-empty-to-${expected}`)
    })
})
