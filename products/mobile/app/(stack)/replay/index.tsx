import type { ReactElement } from 'react'

import { useDataMode } from '@/demo/demoMode'
import { ReplayFeedScreen } from '@/features/replay/feed/ReplayFeedScreen'
import { ReplayListScreen } from '@/features/replay/ReplayListScreen'

import { MobileProductGate } from '@/features/tabs/MobileProductGate'
import { FEATURE_FLAGS, useFeatureFlag } from '@/lib/featureFlags'

export default function ReplayListRoute(): ReactElement {
    // With the feed on, Sessions opens the feed, and Sources in the feed is the list.
    const feed = useFeatureFlag(FEATURE_FLAGS.replayFeed)
    if (useDataMode() === 'demo') {
        return <ReplayFeedScreen />
    }
    return (
        <MobileProductGate flag={FEATURE_FLAGS.sessionReplay}>
            {feed ? <ReplayFeedScreen /> : <ReplayListScreen chrome="stack" />}
        </MobileProductGate>
    )
}
