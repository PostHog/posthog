import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { loadBroadcastNotSent, notSentKind } from './broadcastNotSent'
import { broadcastSentLogic } from './broadcastSentLogic'

describe('broadcastNotSent', () => {
    let queries: string[]

    beforeEach(() => {
        initKeaTests()
        queries = []
        jest.spyOn(api, 'queryHogQL').mockImplementation(async (query: any) => {
            const text = String(query)
            queries.push(text)
            if (text.includes('GROUP BY status')) {
                return {
                    results: [
                        ['failed', 2],
                        ['succeeded', 5],
                        ['canceled', 1],
                    ],
                } as any
            }
            if (text.includes('FROM log_entries') && text.includes('argMax(message')) {
                return {
                    results: [['inv-skipped', 'Skipping send: email sending is paused for this workflow.']],
                } as any
            }
            return {
                results: [
                    ['inv-failed', 'failed', 'Mailbox unavailable.', 'a@example.com', 'person-a'],
                    ['inv-skipped', 'succeeded', '', 'b@example.com', 'person-b'],
                ],
            } as any
        })
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        { status: 'failed', kind: 'failed' },
        { status: 'canceled', kind: 'canceled' },
        // A paused send does not fail the run, so it comes back as a succeeded run that logged an error.
        { status: 'succeeded', kind: 'skipped' },
    ])('maps a $status run to $kind', ({ status, kind }) => {
        expect(notSentKind(status)).toBe(kind)
    })

    it('counts the whole run and takes a missing reason from the run log', async () => {
        const result = await loadBroadcastNotSent('flow-1', 'run-1', '2026-11-12T15:49:00Z')

        expect(result.counts).toEqual({ failed: 2, skipped: 5, canceled: 1 })
        expect(result.rows).toEqual([
            {
                invocationId: 'inv-failed',
                kind: 'failed',
                reason: 'Mailbox unavailable.',
                distinctId: 'a@example.com',
                personId: 'person-a',
            },
            {
                invocationId: 'inv-skipped',
                kind: 'skipped',
                reason: 'Skipping send: email sending is paused for this workflow.',
                distinctId: 'b@example.com',
                personId: 'person-b',
            },
        ])
        expect(queries.every((query) => query.includes("'run-1'") || query.includes('FROM log_entries'))).toBe(true)
    })

    it.each([
        { case: 'an unsaved broadcast', id: 'new', parentRunId: 'run-1' },
        { case: 'no run', id: 'flow-1', parentRunId: null },
    ])('does not query for $case', async ({ id, parentRunId }) => {
        const logic = broadcastSentLogic({ id, parentRunId, runCreatedAt: '2026-11-12T15:49:00Z' })
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadNotSent()).toDispatchActions(['loadNotSentSuccess'])

        expect(queries).toEqual([])
        expect(logic.values.notSent).toEqual({ rows: [], counts: { failed: 0, skipped: 0, canceled: 0 } })
        logic.unmount()
    })
})
