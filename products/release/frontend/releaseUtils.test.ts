import type { EarlyAccessFeatureApi } from 'products/early_access_features/frontend/generated/api.schemas'
import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'
import type { HogFlowApi, SendCalendarFlowApi } from 'products/workflows/frontend/generated/api.schemas'

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

const LAUNCH_SEND = {
    id: 'broadcast-1',
    name: 'Launch email',
    schedules: [{ id: 'schedule-1', next_run_at: '2099-01-02T09:00:00Z' }],
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
            created_at: '2026-10-02T00:00:00Z',
        } as ReleaseDTOApi
        const index = buildReleaseIndex(
            [FLAG],
            [],
            [],
            [],
            { complete: true, resolvedFlagIds: [FLAG.id], unknownFlagIds: [] },
            { broadcasts: [{ id: LAUNCH_SEND.id, name: 'Launch email' } as HogFlowApi], sends: [LAUNCH_SEND] }
        )

        const result = buildReleaseRow(release, index)

        expect(result.events.filter((event) => event.kind === 'broadcast').map((event) => event.upcoming)).toEqual([
            undefined,
            true,
        ])
        expect(result.nextDate).toBe('2099-01-02T09:00:00Z')
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
