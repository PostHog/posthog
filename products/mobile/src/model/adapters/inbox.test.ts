import type { BriefingApi, BriefingItemApi } from '@/api/today'

import { inboxFromBriefing, inboxFromReports } from './inbox'
import { reportFixture } from './testFixtures'

function briefingItem(overrides: Partial<BriefingItemApi>): BriefingItemApi {
    return {
        key: 'report:00000000-0000-0000-0000-000000000001',
        group: 'report',
        source: 'self_driving',
        reason: 'suggested_reviewer',
        title: 'Exports fail for guests',
        rank: 1,
        state: 'open',
        source_product: 'error_tracking',
        report: { priority: 'P1', pull_request_state: null, signal_count: 4, updated_at: '2026-10-09T09:00:00Z' },
        ...overrides,
    }
}

describe('inbox adapters', () => {
    test('keeps only live report items from the briefing, in rank order', () => {
        const briefing: BriefingApi = {
            id: 'b1',
            status: 'ready',
            items: [
                briefingItem({ key: 'report:second', rank: 2, reason: 'waiting_for_you', source_product: 'zendesk' }),
                briefingItem({ key: 'dashboard:7', group: 'dashboard', rank: 3, source_product: null, report: null }),
                briefingItem({ key: 'report:deleted', rank: 4, report: null }),
                briefingItem({ key: 'report:first', rank: 1, state: 'done' }),
            ],
        }
        expect(inboxFromBriefing(briefing)).toMatchObject([
            { id: 'report:first', reportId: 'first', state: 'done', accent: 'resolved', needsInput: false, rank: 1 },
            {
                id: 'report:second',
                reportId: 'second',
                sourceProduct: 'zendesk',
                sourceLabel: 'Zendesk',
                accent: 'opportunity',
                needsInput: true,
                reason: 'waiting_for_you',
            },
        ])
    })

    test('maps the fallback list: input needed, agent claims and closed reports', () => {
        const items = inboxFromReports([
            reportFixture({ id: 'a', status: 'pending_input', source_products: ['signals_scout', 'session_replay'] }),
            reportFixture({
                id: 'b',
                assignee: { kind: 'task', user: null, task_id: 't1', agent: null, claimed_at: null },
            }),
            reportFixture({ id: 'c', status: 'resolved', source_products: ['freshdesk'] }),
        ])
        expect(items).toMatchObject([
            { reportId: 'a', needsInput: true, sourceProduct: 'session_replay', accent: 'alert', state: 'open' },
            { reportId: 'b', needsInput: false, agent: { name: 'PostHog', mark: 'ph' } },
            { reportId: 'c', state: 'done', accent: 'resolved', sourceProduct: 'other', sourceLabel: 'Report' },
        ])
        expect(items[0]?.agent).toBeUndefined()
    })
})
