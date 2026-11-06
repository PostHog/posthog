import type { GoalScoutEvidenceApi, GoalScoutWorkApi } from 'products/signals/frontend/generated/api.schemas'

import { ideaEvidence, ideaReason } from './ideas'

function idea(patch: Partial<GoalScoutWorkApi>): GoalScoutWorkApi {
    return { summary: '', evidence: [], ...patch } as GoalScoutWorkApi
}

function evidence(kind: GoalScoutEvidenceApi['kind'], label: string): GoalScoutEvidenceApi {
    return { kind, label, url: `/${label}` }
}

describe('goal ideas', () => {
    it.each([
        [
            'Supported. People who see a sample upload twice as often. A second line.',
            'People who see a sample upload twice as often.',
        ],
        ['Not supported. Uploads finish in 2.1 s. People leave before upload.', 'Uploads finish in 2.1 s.'],
        ['not supported: Few people use the coupon field.', 'Few people use the coupon field.'],
        ['People who see a sample upload more.', 'People who see a sample upload more.'],
    ])('takes the reason from the summary %#', (summary, reason) => {
        expect(ideaReason(idea({ summary }))).toBe(reason)
    })

    it('keeps PostHog evidence only, replays first, then insights and charts in their order', () => {
        const item = idea({
            evidence: [
                evidence('link', 'repo#15'),
                evidence('chart', 'chart'),
                evidence('experiment', 'experiment'),
                evidence('insight', 'insight'),
                evidence('error', 'error'),
                evidence('replay', 'replay'),
                evidence('link', 'report'),
            ],
        })
        expect(ideaEvidence(item).map((entry) => entry.label)).toEqual([
            'replay',
            'chart',
            'insight',
            'error',
            'experiment',
        ])
    })
})
