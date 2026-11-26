import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { TeamPublicType, TeamType } from '~/types'

// The flags service enforces saved entries whatever the flag says, so admins must be able to clear them.
export function isRequestAllowlistVisible(team: TeamType | TeamPublicType | null): boolean {
    const policy = team?.feature_flag_policy_config
    return (
        !!featureFlagLogic.findMounted()?.values.featureFlags[FEATURE_FLAGS.FEATURE_FLAG_REQUEST_ALLOWLIST] ||
        !!policy?.allowed_hosts?.length ||
        !!policy?.allowed_ips?.length
    )
}
