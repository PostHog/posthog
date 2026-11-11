import type { ReactElement } from 'react'
import { ReplayListScreen } from '@/features/replay/ReplayListScreen'
import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { TabScene } from '@/features/tabs/TabScene'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ReplayTabRoute(): ReactElement {
    return (
        <TabScene tab="replay">
            <MobileProductGate flag={FEATURE_FLAGS.sessionReplay}>
                <ReplayListScreen chrome="tab" />
            </MobileProductGate>
        </TabScene>
    )
}
