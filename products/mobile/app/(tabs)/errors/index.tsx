import type { ReactElement } from 'react'
import { ErrorsListScreen } from '@/features/errors/ErrorsListScreen'
import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { TabScene } from '@/features/tabs/TabScene'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ErrorsTabRoute(): ReactElement {
    return (
        <TabScene>
            <MobileProductGate flag={FEATURE_FLAGS.errorTracking}>
                <ErrorsListScreen chrome="tab" />
            </MobileProductGate>
        </TabScene>
    )
}
