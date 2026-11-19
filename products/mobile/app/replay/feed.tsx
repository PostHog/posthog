import type { ReactElement } from 'react'

import { useDataMode } from '@/demo/demoMode'
import { ReplayFeedScreen } from '@/features/replay/feed/ReplayFeedScreen'
import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ReplayFeedRoute(): ReactElement {
    if (useDataMode() === 'demo') {
        return <ReplayFeedScreen />
    }
    return (
        <MobileProductGate flag={FEATURE_FLAGS.sessionReplay}>
            <MobileProductGate flag={FEATURE_FLAGS.replayFeed}>
                <ReplayFeedScreen />
            </MobileProductGate>
        </MobileProductGate>
    )
}
