import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { parseSeekSeconds, sessionOpenSource } from '@/features/replay/replayLinks'
import { SessionScreen } from '@/features/replay/SessionScreen'

import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS } from '@/lib/featureFlags'

export default function SessionRoute(): ReactElement {
    const { sessionId, t, source } = useLocalSearchParams<{ sessionId: string; t?: string; source?: string }>()
    return (
        <MobileProductGate flag={FEATURE_FLAGS.sessionReplay}>
            <SessionScreen
                key={sessionId}
                sessionId={sessionId ?? ''}
                t={parseSeekSeconds(t)}
                source={sessionOpenSource(source)}
            />
        </MobileProductGate>
    )
}
