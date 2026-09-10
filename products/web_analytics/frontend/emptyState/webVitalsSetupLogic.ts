import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { eventDefinitionsList } from 'products/event_definitions/frontend/generated/api'

/**
 * Setup detection for the web vitals empty state (the web vitals tab of web
 * analytics - the analytics tabs are not gated). Three-state: a `$web_vitals`
 * event definition exists → has-data; autocapture opted in without one yet →
 * waiting-for-data; neither → needs-setup.
 */
export const webVitalsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.WEB_ANALYTICS,
    path: ['products', 'web_analytics', 'frontend', 'emptyState', 'webVitalsSetupLogic'],
    detect: async () => {
        const teamId = teamLogic.findMounted()?.values.currentTeamId
        if (!teamId) {
            return 'unknown'
        }
        const response = await eventDefinitionsList(String(teamId), { names: ['$web_vitals'], limit: 1 })
        if (response.results.some((definition) => definition.name === '$web_vitals')) {
            return 'has-data'
        }
        return teamLogic.findMounted()?.values.currentTeam?.autocapture_web_vitals_opt_in
            ? 'waiting-for-data'
            : 'needs-setup'
    },
    pollIntervalMs: 20000,
    // Enabling autocapture (from this empty state or settings) must flip the
    // screen to "waiting" right away, not on the next poll tick.
    recheckActionTypes: () => [teamLogic.actionTypes.updateCurrentTeamSuccess],
})
