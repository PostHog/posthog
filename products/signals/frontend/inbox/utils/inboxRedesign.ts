import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

/**
 * Whether the inbox shows the redesign (report sections, triage mode, the Settings tab, scout
 * cards) or the layout it replaces. One reader for every logic, so the flag key is written once.
 * Components read the same flag through `useFeatureFlag('INBOX_REDESIGN')`.
 */
export function isInboxRedesignEnabled(featureFlags: FeatureFlagsSet): boolean {
    return !!featureFlags[FEATURE_FLAGS.INBOX_REDESIGN]
}
