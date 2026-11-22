import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { featureFlagsList } from 'products/feature_flags/frontend/generated/api'
import { FeatureFlagsListArchived } from 'products/feature_flags/frontend/generated/api.schemas'

/**
 * Setup detection for the feature flags empty state. Flags are a creation-first
 * product, so "set up" simply means the project has at least one flag - no event
 * or traffic signal involved. A remembered has-data answer opens the scene without
 * a flag check, and a background check forgets it once the project has no flags.
 */
export const featureFlagsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.FEATURE_FLAGS,
    path: ['products', 'feature_flags', 'frontend', 'emptyState', 'featureFlagsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const live = await featureFlagsList(projectId, { limit: 1 })
        if (live.count > 0) {
            return 'has-data'
        }
        // The list excludes archived flags unless asked for them, and no value of
        // `archived` returns both, so a project that archived all of its flags would
        // count zero and lose the scene it unarchives them from.
        const archived = await featureFlagsList(projectId, { limit: 1, archived: FeatureFlagsListArchived.True })
        return archived.count > 0 ? 'has-data' : 'needs-setup'
    },
    // Undo of a deleted flag brings it back without remounting the gate, so no flag check runs on its own.
    // The flag list reloads after Undo, and that reload is the signal to check again.
    recheckActionTypes: () => [featureFlagsLogic.actionTypes.loadFeatureFlagsSuccess],
    statusFromRecheck: ({ featureFlags }) => (featureFlags.count > 0 ? 'has-data' : null),
    cacheHasData: true,
    revalidateCachedHasData: true,
})
