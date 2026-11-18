import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { ReplayFeedScreen } from '@/features/replay/feed/ReplayFeedScreen'
import { ReplayListScreen } from '@/features/replay/ReplayListScreen'

import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS, useFeatureFlag } from '@/lib/featureFlags'

export default function ReplayListRoute(): ReactElement {
    // With the feed on, Sessions opens the feed; its More menu comes back here with `view=list` for the list.
    const feed = useFeatureFlag(FEATURE_FLAGS.replayFeed)
    const { view } = useLocalSearchParams<{ view?: string }>()
    return (
        <MobileProductGate flag={FEATURE_FLAGS.sessionReplay}>
            {feed && view !== 'list' ? <ReplayFeedScreen /> : <ReplayListScreen chrome="stack" />}
        </MobileProductGate>
    )
}
