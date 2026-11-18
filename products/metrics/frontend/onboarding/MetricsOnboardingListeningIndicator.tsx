import { SetupListeningIndicator } from 'lib/components/ProductEmptyState/SetupListeningIndicator'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { metricsSetupLogic } from '../emptyState/metricsSetupLogic'

export function MetricsOnboardingListeningIndicator(): JSX.Element {
    return (
        <SetupListeningIndicator
            productKey={ProductKey.METRICS}
            statusLogic={metricsSetupLogic}
            dataName="metric"
            destination={{ label: 'Metrics', url: urls.metrics() }}
        />
    )
}
