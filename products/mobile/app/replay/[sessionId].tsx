import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { parseSeekSeconds, sessionOpenSource } from '@/features/replay/replayLinks'
import { SessionScreen } from '@/features/replay/SessionScreen'

export default function SessionRoute(): ReactElement {
    const { sessionId, t, source } = useLocalSearchParams<{ sessionId: string; t?: string; source?: string }>()
    return (
        <SessionScreen
            key={sessionId}
            sessionId={sessionId ?? ''}
            t={parseSeekSeconds(t)}
            source={sessionOpenSource(source)}
        />
    )
}
