import type { ErrorTrackingRecommendationApi } from '../../../generated/api.schemas'

export type ErrorTrackingBannerKey = 'source_maps' | 'alerts' | 'rate_limits'

/** `pending` means the first compute for this banner's check is still running. */
export type BannerCandidateState = 'pending' | 'needed' | 'not_needed'

export interface BannerCandidate {
    key: ErrorTrackingBannerKey
    state: BannerCandidateState
    dismissed: boolean
}

export function candidateState<T extends ErrorTrackingRecommendationApi>(
    recommendation: T | null,
    isNeeded: (recommendation: T) => boolean
): BannerCandidateState {
    if (!recommendation) {
        return 'not_needed'
    }
    if (recommendation.computed_at === null) {
        // A failed first compute reverts to ready with no result. Skip it so it can't hold back the queue.
        return recommendation.status === 'computing' ? 'pending' : 'not_needed'
    }
    return isNeeded(recommendation) ? 'needed' : 'not_needed'
}

/**
 * Candidates arrive in priority order. Returns every banner that applies, in that order. A pending
 * candidate cuts the list there, so a lower banner never shows and then gets pushed down when the
 * higher one resolves.
 */
export function activeBanners(candidates: BannerCandidate[]): ErrorTrackingBannerKey[] {
    const active: ErrorTrackingBannerKey[] = []
    for (const candidate of candidates) {
        if (candidate.dismissed) {
            continue
        }
        if (candidate.state === 'pending') {
            return active
        }
        if (candidate.state === 'needed') {
            active.push(candidate.key)
        }
    }
    return active
}

export function currentBanner(
    active: ErrorTrackingBannerKey[],
    selected: ErrorTrackingBannerKey | null
): ErrorTrackingBannerKey | null {
    return selected && active.includes(selected) ? selected : (active[0] ?? null)
}

export function stepBanner(
    active: ErrorTrackingBannerKey[],
    current: ErrorTrackingBannerKey | null,
    direction: 'previous' | 'next'
): ErrorTrackingBannerKey | null {
    const index = current ? active.indexOf(current) : -1
    if (direction === 'next') {
        return active[(index + 1) % active.length] ?? null
    }
    return active[Math.max(index - 1, 0)] ?? null
}

export function bannerAfterDismiss(
    active: ErrorTrackingBannerKey[],
    dismissed: ErrorTrackingBannerKey
): ErrorTrackingBannerKey | null {
    const index = active.indexOf(dismissed)
    return active[index + 1] ?? active[index - 1] ?? null
}
