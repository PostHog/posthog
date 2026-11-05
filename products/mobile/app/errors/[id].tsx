import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { issueOpenSourceParam } from '@/features/errors/analytics'
import { IssueScreen } from '@/features/errors/IssueScreen'
import { windowParam } from '@/features/errors/issueModel'

import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function IssueRoute(): ReactElement {
    const { id, from, window } = useLocalSearchParams<{ id: string; from?: string; window?: string }>()
    return (
        <MobileProductGate flag={FEATURE_FLAGS.errorTracking}>
            <IssueScreen issueId={id ?? ''} from={issueOpenSourceParam(from)} window={windowParam(window)} />
        </MobileProductGate>
    )
}
