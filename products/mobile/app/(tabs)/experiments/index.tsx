import type { ReactElement } from 'react'
import { ExperimentsListScreen } from '@/features/experiments/ExperimentsListScreen'
import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { TabScene } from '@/features/tabs/TabScene'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ExperimentsTabRoute(): ReactElement {
    return (
        <TabScene tab="experiments">
            <MobileProductGate flag={FEATURE_FLAGS.experiments}>
                <ExperimentsListScreen chrome="tab" />
            </MobileProductGate>
        </TabScene>
    )
}
