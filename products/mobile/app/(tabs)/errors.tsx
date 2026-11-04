import type { ReactElement } from 'react'

import { ErrorsListScreen } from '@/features/errors/ErrorsListScreen'

import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function ErrorsTabRoute(): ReactElement {
    return (
        <MobileProductGate flag={FEATURE_FLAGS.errorTracking}>
            <ErrorsListScreen chrome="tab" />
        </MobileProductGate>
    )
}
