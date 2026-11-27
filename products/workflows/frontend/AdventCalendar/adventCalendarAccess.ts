import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

const FLAG = FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR

export function adventCalendarAccess(
    featureFlags: FeatureFlagsSet,
    receivedFeatureFlags: boolean
): boolean | undefined {
    const pageDecision = window.POSTHOG_USER_IDENTITY_WITH_FLAGS?.featureFlags?.[FLAG]
    if (
        window.POSTHOG_GLOBAL_ERRORS?.onFeatureFlagsLoadError &&
        typeof pageDecision === 'boolean' &&
        posthog.getFeatureFlag(FLAG, { fresh: true, send_event: false }) === undefined
    ) {
        return pageDecision
    }
    return receivedFeatureFlags ? !!featureFlags[FLAG] : undefined
}
