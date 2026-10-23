import type { ErrorTrackingRecommendationApi } from '../../../generated/api.schemas'
import {
    activeBanners,
    bannerAfterDismiss,
    BannerCandidateState,
    candidateState,
    ErrorTrackingBannerKey,
    stepBanner,
} from './bannerQueue'

const recommendation = (overrides: Partial<ErrorTrackingRecommendationApi> = {}): ErrorTrackingRecommendationApi => ({
    id: 'recommendation',
    type: 'source_maps',
    meta: {},
    completed: false,
    status: 'ready',
    computed_at: '2024-07-08T00:00:00Z',
    dismissed_at: null,
    created_at: '2024-07-08T00:00:00Z',
    updated_at: '2024-07-08T00:00:00Z',
    ...overrides,
})

describe('banner queue', () => {
    test.each<[string, ErrorTrackingRecommendationApi | null, BannerCandidateState]>([
        ['missing row', null, 'not_needed'],
        ['first compute running', recommendation({ computed_at: null, status: 'computing' }), 'pending'],
        ['first compute failed', recommendation({ computed_at: null, status: 'ready' }), 'not_needed'],
        ['recompute running over an old result', recommendation({ status: 'computing' }), 'needed'],
        ['completed', recommendation({ completed: true }), 'not_needed'],
    ])('candidate state: %s', (_, input, expected) => {
        expect(candidateState(input, (r) => !r.completed)).toEqual(expected)
    })

    const KEYS: ErrorTrackingBannerKey[] = ['source_maps', 'alerts', 'rate_limits']

    test.each<[string, [BannerCandidateState, boolean][], ErrorTrackingBannerKey[]]>([
        [
            'keeps priority order',
            [
                ['needed', false],
                ['needed', false],
                ['needed', false],
            ],
            KEYS,
        ],
        [
            'skips dismissed',
            [
                ['needed', true],
                ['needed', false],
                ['needed', false],
            ],
            ['alerts', 'rate_limits'],
        ],
        [
            'skips fixed',
            [
                ['needed', false],
                ['not_needed', false],
                ['needed', false],
            ],
            ['source_maps', 'rate_limits'],
        ],
        [
            'pending cuts the list there',
            [
                ['needed', false],
                ['pending', false],
                ['needed', false],
            ],
            ['source_maps'],
        ],
        [
            'dismissed while pending does not cut',
            [
                ['pending', true],
                ['needed', false],
                ['needed', false],
            ],
            ['alerts', 'rate_limits'],
        ],
        [
            'all dismissed is empty',
            [
                ['needed', true],
                ['needed', true],
                ['needed', true],
            ],
            [],
        ],
    ])('active banners: %s', (_, candidates, expected) => {
        expect(
            activeBanners(candidates.map(([state, dismissed], index) => ({ key: KEYS[index], state, dismissed })))
        ).toEqual(expected)
    })

    test.each<[string, ErrorTrackingBannerKey, 'previous' | 'next', ErrorTrackingBannerKey]>([
        ['next from the middle', 'alerts', 'next', 'rate_limits'],
        ['previous from the middle', 'alerts', 'previous', 'source_maps'],
        ['next from the last wraps to the first', 'rate_limits', 'next', 'source_maps'],
        ['previous stops at the start', 'source_maps', 'previous', 'source_maps'],
    ])('step: %s', (_, current, direction, expected) => {
        expect(stepBanner(KEYS, current, direction)).toEqual(expected)
    })

    test.each<[string, ErrorTrackingBannerKey[], ErrorTrackingBannerKey, ErrorTrackingBannerKey | null]>([
        ['moves to the next one', KEYS, 'alerts', 'rate_limits'],
        ['falls back to the previous one at the end', KEYS, 'rate_limits', 'alerts'],
        ['empties when the last one goes', ['alerts'], 'alerts', null],
    ])('after dismiss: %s', (_, active, dismissed, expected) => {
        expect(bannerAfterDismiss(active, dismissed)).toEqual(expected)
    })
})
