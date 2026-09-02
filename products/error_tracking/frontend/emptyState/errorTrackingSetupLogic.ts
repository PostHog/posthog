import { ApiRequest } from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

/**
 * Setup detection for the error tracking empty state. An issue existing means
 * exceptions have been captured and grouped; with none, exception autocapture
 * being opted in means the JS SDK will start capturing on its own - the project
 * is instrumented, an exception just hasn't happened yet.
 */
export const errorTrackingSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.ERROR_TRACKING,
    path: ['products', 'error_tracking', 'frontend', 'emptyState', 'errorTrackingSetupLogic'],
    detect: async () => {
        const response = await new ApiRequest().errorTrackingIssuesExists().get()
        if (response?.exists === true) {
            return 'has-data'
        }
        return teamLogic.findMounted()?.values.currentTeam?.autocapture_exceptions_opt_in
            ? 'waiting-for-data'
            : 'needs-setup'
    },
    pollIntervalMs: 20000,
    // Enabling autocapture (from this empty state or settings) must flip the
    // screen to "waiting" right away, not on the next poll tick.
    recheckActionTypes: () => [teamLogic.actionTypes.updateCurrentTeamSuccess],
})
