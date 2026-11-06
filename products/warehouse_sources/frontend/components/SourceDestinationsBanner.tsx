import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

/** Points someone looking at their own warehouse at the other half of the same connection.
 *
 * Batch exports and warehouse source destinations write to the same seven warehouses from the
 * same saved connections, so a person who has connected one for exports has already done the
 * work to receive imported rows there too, and usually does not know it.
 */
export function SourceDestinationsBanner(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    // The destinations scene is behind the same flag, so without it this would offer a dead link.
    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION]) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            dismissKey="warehouse-source-destinations-cross-sell"
            action={{
                children: 'Get started',
                // Sources, not destinations: a destination is turned on from the source that
                // feeds it, so the destinations page would only tell a reader to go here.
                to: urls.sources(),
                'data-attr': 'warehouse-destinations-cross-sell',
            }}
        >
            PostHog also runs ELT pipelines. A pipeline imports tables from a source like Stripe or HubSpot, and can
            write them to the same warehouse you export to, over the same connection.
        </LemonBanner>
    )
}
