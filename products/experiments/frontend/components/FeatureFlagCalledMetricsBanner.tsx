import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { getEventPropertiesForExperiment } from 'lib/utils/eventUsageLogic'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

export function FeatureFlagCalledMetricsBanner(): JSX.Element | null {
    const { experiment, featureFlagCalledMetricNames } = useValues(experimentLogic)
    const metricCount = featureFlagCalledMetricNames.length

    useEffect(() => {
        if (metricCount > 0) {
            // pinned: analytics event name, renaming it breaks the insights that count it
            posthog.capture('experiment feature flag called metrics warning shown', {
                ...getEventPropertiesForExperiment(experiment),
                metric_count: metricCount,
            })
        }
        // Report once per experiment and metric count. The experiment object changes on every edit and save.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [experiment.id, metricCount])

    if (metricCount === 0) {
        return null
    }

    return (
        <LemonBanner className="mb-4" type="warning">
            <div>
                <strong>
                    We're reducing how long PostHog keeps <code>$feature_flag_called</code> events
                </strong>
            </div>
            <div>
                Switch metrics that use this event to the <code>$experiment_exposure</code> event to keep them working.
                Metrics to update: <strong>{featureFlagCalledMetricNames.join(', ')}</strong>
            </div>
            <div>
                <Link
                    to="https://posthog.com/blog/changing-event-storage"
                    target="_blank"
                    data-attr="experiment-feature-flag-called-metrics-blog-link"
                >
                    Read more about the change
                </Link>
            </div>
        </LemonBanner>
    )
}
