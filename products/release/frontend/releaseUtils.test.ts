import type { EarlyAccessFeatureApi } from 'products/early_access_features/frontend/generated/api.schemas'
import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'
import type { SendCalendarFlowApi } from 'products/workflows/frontend/generated/api.schemas'

import type { ReleaseDTOApi } from './generated/api.schemas'
import { LinkCandidate, buildReleaseIndex, buildReleaseRow, rankLinkSuggestions } from './releaseUtils'

const FLAG = {
    id: 1,
    key: 'quiet-theme',
    active: true,
    deleted: false,
    archived: false,
    created_at: '2026-10-01T00:00:00Z',
    filters: { groups: [{ properties: [], rollout_percentage: 100 }] },
    experiment_set: [],
} as unknown as FeatureFlagApi

function row(hasHiddenFlags: boolean, flags: FeatureFlagApi[] = [FLAG]): ReturnType<typeof buildReleaseRow> {
    const release = {
        id: 'release-1',
        name: 'Quiet theme',
        description: '',
        owner: null,
        feature_flag_ids: flags.map((flag) => flag.id),
        has_hidden_flags: hasHiddenFlags,
        broadcast_ids: [],
        broadcasts: [],
        created_at: '2026-10-02T00:00:00Z',
    } as ReleaseDTOApi
    const index = buildReleaseIndex([FLAG], [], [], [], {
        complete: true,
        resolvedFlagIds: [FLAG.id],
        unknownFlagIds: [],
    })
    return buildReleaseRow(release, index)
}

const ARCHIVED_EARLY_ACCESS = {
    id: 'ea-1',
    name: 'Quiet theme beta',
    stage: 'archived',
    created_at: '2026-10-03T00:00:00Z',
    feature_flag: { key: FLAG.key },
} as unknown as EarlyAccessFeatureApi

const NEXT_SEND = new Date(Math.floor((Date.now() + 3 * 86_400_000) / 1000) * 1000).toISOString()

const LAUNCH_SEND = {
    id: 'broadcast-1',
    name: 'Launch email',
    schedules: [
        {
            id: 'schedule-1',
            rrule: 'FREQ=DAILY;COUNT=1',
            starts_at: NEXT_SEND,
            timezone: 'UTC',
            status: 'active',
            next_run_at: NEXT_SEND,
        },
    ],
    batch_jobs: [{ id: 'job-1', status: 'completed', created_at: '2026-10-05T09:00:00Z' }],
} as unknown as SendCalendarFlowApi

describe('buildReleaseRow', () => {
    it('shows the sends of a linked broadcast and stops suggesting one', () => {
        const release = {
            id: 'release-1',
            name: 'Quiet theme',
            description: '',
            owner: null,
            feature_flag_ids: [FLAG.id],
            has_hidden_flags: false,
            broadcast_ids: [LAUNCH_SEND.id],
            broadcasts: [{ id: LAUNCH_SEND.id, name: 'Launch email', status: 'active', recent_sends: [] }],
            created_at: '2026-10-02T00:00:00Z',
        } as ReleaseDTOApi
        const index = buildReleaseIndex(
            [FLAG],
            [],
            [],
            [],
            { complete: true, resolvedFlagIds: [FLAG.id], unknownFlagIds: [] },
            {
                broadcasts: [{ id: LAUNCH_SEND.id, name: 'Launch email', status: 'active', recent_sends: [] }],
                sends: [LAUNCH_SEND],
                runs: {
                    [LAUNCH_SEND.id]: [
                        { id: 'job-1', status: 'completed', created_at: '2026-10-05T09:00:00Z' },
                        { id: 'job-2', status: 'failed', created_at: '2026-10-06T09:00:00Z' },
                    ],
                },
            }
        )

        const result = buildReleaseRow(release, index)

        expect(
            result.events
                .filter((event) => event.kind === 'broadcast')
                .map((event) => [event.title.split(':')[0], event.upcoming])
        ).toEqual([
            ['Broadcast sent', undefined],
            ['Broadcast failed', undefined],
            ['Broadcast scheduled', true],
        ])
        expect(result.nextDate).toBe(NEXT_SEND)
        expect(result.suggestions.map((suggestion) => suggestion.key)).not.toContain('broadcast')
    })

    it('keeps an archived early access feature in the history without an enrollment bar', () => {
        const release = {
            id: 'release-1',
            name: 'Quiet theme',
            description: '',
            owner: null,
            feature_flag_ids: [FLAG.id],
            has_hidden_flags: false,
            broadcast_ids: [],
            broadcasts: [],
            created_at: '2026-10-02T00:00:00Z',
        } as ReleaseDTOApi
        const index = buildReleaseIndex([FLAG], [], [ARCHIVED_EARLY_ACCESS], [], {
            complete: true,
            resolvedFlagIds: [FLAG.id],
            unknownFlagIds: [],
        })

        const result = buildReleaseRow(release, index)

        expect(result.earlyAccess).toEqual([ARCHIVED_EARLY_ACCESS])
        expect(result.events.some((event) => event.key === 'ea-ea-1')).toBe(true)
        expect(result.spans.some((span) => span.kind === 'early_access')).toBe(false)
        expect(result.suggestions.map((suggestion) => suggestion.key)).not.toContain('early-access')
    })

    it('waits for linked flags that have not loaded yet instead of asking to link one', () => {
        const release = {
            id: 'release-1',
            name: 'Quiet theme',
            description: '',
            owner: null,
            feature_flag_ids: [FLAG.id],
            has_hidden_flags: false,
            broadcast_ids: [],
            broadcasts: [],
            created_at: '2026-10-02T00:00:00Z',
        } as ReleaseDTOApi
        const index = buildReleaseIndex([], [], [], [], { complete: true, resolvedFlagIds: [], unknownFlagIds: [] })

        const result = buildReleaseRow(release, index)

        expect([result.stage, result.status, result.nextStep?.title]).toEqual(['flag', 'Loading flags…', undefined])
    })

    it.each([
        ['every linked flag is visible', false, [FLAG], 'released', 'Clean up the flag', false],
        ['a linked flag is hidden from the caller', true, [FLAG], 'flag', undefined, false],
        ['every linked flag is hidden from the caller', true, [], 'flag', undefined, false],
        ['no flag is linked', false, [], 'planned', 'Link a feature flag', true],
    ])('when %s', (_name, hasHiddenFlags, flags, stage, nextStep, needsDecision) => {
        const result = row(hasHiddenFlags, flags)

        expect(result.stage).toBe(stage)
        expect(result.nextStep?.title).toBe(nextStep)
        expect(result.needsDecision).toBe(needsDecision)
    })

    it('counts only flags open to all users toward the flags that reach everyone', () => {
        const targeted = {
            ...FLAG,
            id: 2,
            key: 'quiet-theme-paid',
            filters: { groups: [{ properties: [{ key: 'plan', value: 'paid' }], rollout_percentage: 100 }] },
        } as unknown as FeatureFlagApi
        const release = {
            id: 'release-1',
            name: 'Quiet theme',
            description: '',
            owner: null,
            feature_flag_ids: [FLAG.id, targeted.id],
            has_hidden_flags: false,
            broadcast_ids: [],
            broadcasts: [],
            created_at: '2026-10-02T00:00:00Z',
        } as ReleaseDTOApi
        const index = buildReleaseIndex([FLAG, targeted], [], [], [], {
            complete: true,
            resolvedFlagIds: [FLAG.id, targeted.id],
            unknownFlagIds: [],
        })

        expect(buildReleaseRow(release, index).headline).toBe('1 of 2 flags reach everyone')
    })
})

describe('broadcast suggestion', () => {
    it('links the new broadcast to the release without asking for an audience', () => {
        const suggestion = row(false).suggestions.find((item) => item.key === 'broadcast')
        const params = new URL(suggestion?.to ?? '', 'https://example.com').searchParams

        expect([params.get('source_record'), params.has('audience')]).toEqual(['release:release-1', false])
    })
})

describe('rankLinkSuggestions', () => {
    const candidate = (kind: LinkCandidate['kind'], label: string): LinkCandidate => ({
        key: `${kind}:${label}`,
        kind,
        id: label,
        label,
    })

    it('ranks candidates by the words they share with the release name', () => {
        const ranked = rankLinkSuggestions('Quiet theme for long sessions', [
            candidate('flag', 'dark-mode'),
            candidate('broadcast', 'Quiet theme: launch email'),
            candidate('flag', 'quiet-mode'),
            candidate('flag', 'quiet-theme'),
        ])

        expect(ranked.map((item) => item.label)).toEqual(['Quiet theme: launch email', 'quiet-theme', 'quiet-mode'])
    })

    it('suggests nothing when the release name has no meaningful words', () => {
        expect(rankLinkSuggestions('New release', [candidate('flag', 'new-release')])).toEqual([])
    })
})
