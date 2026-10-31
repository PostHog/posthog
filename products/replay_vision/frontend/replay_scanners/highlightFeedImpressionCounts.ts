import { chunk } from 'lib/utils/arrays'
import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'

import { visionScannersHighlightFeedImpressionsCreate } from '../generated/api'

// The impressions endpoint takes at most this many ids per request.
const IMPRESSIONS_BATCH_SIZE = 100

/** Tells the server which cards one feed load showed, so the feed ranks them lower next time. Best effort:
 * a lost batch only means a card ranks a little higher on the next load. */
export function recordFeedImpressions(feedLoadId: string, observationIds: string[]): void {
    const teamId = getCurrentTeamIdOrNone()
    if (!teamId) {
        return
    }
    for (const ids of chunk(observationIds, IMPRESSIONS_BATCH_SIZE)) {
        void visionScannersHighlightFeedImpressionsCreate(String(teamId), {
            feed_load_id: feedLoadId,
            observation_ids: ids,
        }).catch(() => {})
    }
}
