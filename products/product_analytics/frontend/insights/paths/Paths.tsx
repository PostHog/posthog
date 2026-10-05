import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { PathsChart } from './PathsChart'
import { PathsLegacy } from './PathsLegacy'

export function Paths(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_PATHS_SANKEY_CHART] ? <PathsChart /> : <PathsLegacy />
}
