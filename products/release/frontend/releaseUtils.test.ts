import type { EarlyAccessFeatureApi } from 'products/early_access_features/frontend/generated/api.schemas'
import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'

import type { ReleaseDTOApi } from './generated/api.schemas'
import { buildReleaseIndex, buildReleaseRow } from './releaseUtils'

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

describe('buildReleaseRow', () => {
    it('keeps an archived early access feature in the history without an enrollment bar', () => {
        const release = {
            id: 'release-1',
            name: 'Quiet theme',
            description: '',
            owner: null,
            feature_flag_ids: [FLAG.id],
            has_hidden_flags: false,
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
