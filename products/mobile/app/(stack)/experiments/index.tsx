import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'
import { ExperimentLinkScope } from '@/features/experiments/ExperimentLinkScope'
import { ExperimentsListScreen } from '@/features/experiments/ExperimentsListScreen'
import { routeParam } from '@/features/report/reportLinkScope'

import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ExperimentsRoute(): ReactElement {
    const params = useLocalSearchParams()
    return (
        <MobileProductGate flag={FEATURE_FLAGS.experiments}>
            <ExperimentLinkScope project={routeParam(params.project)} host={routeParam(params.host)}>
                <ExperimentsListScreen chrome="stack" />
            </ExperimentLinkScope>
        </MobileProductGate>
    )
}
