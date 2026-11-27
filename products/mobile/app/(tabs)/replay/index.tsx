import type { ReactElement } from 'react'
import { useDataMode } from '@/demo/demoMode'
import { ReplayListScreen } from '@/features/replay/ReplayListScreen'
import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { TabScene } from '@/features/tabs/TabScene'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ReplayTabRoute(): ReactElement {
    const demo = useDataMode() === 'demo'
    return (
        <TabScene tab="replay">
            {demo ? (
                <ReplayListScreen chrome="tab" />
            ) : (
                <MobileProductGate flag={FEATURE_FLAGS.sessionReplay}>
                    <ReplayListScreen chrome="tab" />
                </MobileProductGate>
            )}
        </TabScene>
    )
}
