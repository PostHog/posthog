import type { ReactElement } from 'react'

import { ExperimentsListScreen } from '@/features/experiments/ExperimentsListScreen'

import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ExperimentsRoute(): ReactElement {
    return (
        <MobileProductGate flag={FEATURE_FLAGS.experiments}>
            <ExperimentsListScreen chrome="stack" />
        </MobileProductGate>
    )
}
