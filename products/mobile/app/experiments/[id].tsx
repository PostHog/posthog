import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { experimentOpenSourceParam } from '@/features/experiments/analytics'
import { ExperimentScreen } from '@/features/experiments/ExperimentScreen'
import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ExperimentRoute(): ReactElement {
    const { id, source, from } = useLocalSearchParams<{ id: string; source?: string; from?: string }>()
    return (
        <MobileProductGate flag={FEATURE_FLAGS.experiments}>
            <ExperimentScreen experimentId={id ?? ''} from={experimentOpenSourceParam(source ?? from)} />
        </MobileProductGate>
    )
}
