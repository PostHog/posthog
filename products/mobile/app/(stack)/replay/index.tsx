import type { ReactElement } from 'react'

import { ReplayListScreen } from '@/features/replay/ReplayListScreen'

import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ReplayListRoute(): ReactElement {
    return (
        <MobileProductGate flag={FEATURE_FLAGS.sessionReplay}>
            <ReplayListScreen chrome="stack" />
        </MobileProductGate>
    )
}
