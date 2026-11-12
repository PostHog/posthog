import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { experimentOpenSourceParam } from '@/features/experiments/analytics'
import { ExperimentLinkScope } from '@/features/experiments/ExperimentLinkScope'
import { ExperimentScreen } from '@/features/experiments/ExperimentScreen'
import { routeParam } from '@/features/report/reportLinkScope'
import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ExperimentRoute(): ReactElement {
    const params = useLocalSearchParams()
    const { id, source, from } = params
    return (
        <MobileProductGate flag={FEATURE_FLAGS.experiments}>
            <ExperimentLinkScope project={routeParam(params.project)} host={routeParam(params.host)}>
                <ExperimentScreen
                    experimentId={routeParam(id) ?? ''}
                    from={experimentOpenSourceParam(routeParam(source) ?? routeParam(from))}
                />
            </ExperimentLinkScope>
        </MobileProductGate>
    )
}
