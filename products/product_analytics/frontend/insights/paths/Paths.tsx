import { useValues } from 'kea'
import { Suspense, lazy } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { retryImport } from 'lib/utils/retryImport'

import { PathsLegacy } from './PathsLegacy'

// Loaded on demand so users on the legacy renderer do not download the Sankey chart.
const PathsChart = lazy(() => retryImport(() => import('./PathsChart').then((m) => ({ default: m.PathsChart }))))

export function Paths(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_PATHS_SANKEY_CHART]) {
        return <PathsLegacy />
    }
    return (
        <Suspense
            fallback={
                <div className="flex h-full w-full items-center justify-center">
                    <Spinner />
                </div>
            }
        >
            <PathsChart />
        </Suspense>
    )
}
