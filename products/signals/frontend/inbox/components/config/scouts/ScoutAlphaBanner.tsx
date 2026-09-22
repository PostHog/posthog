import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'

/**
 * Announcement banner above the roster, sourced from the `signals-scout` flag payload via the scout
 * metadata endpoint. Operator-controlled so a rollout or run-limit notice can change without a
 * frontend deploy; nothing renders when the payload carries no message.
 */
export function ScoutAlphaBanner({ className }: { className?: string }): JSX.Element | null {
    const { scoutBannerMessage } = useValues(scoutFleetLogic)
    if (!scoutBannerMessage) {
        return null
    }
    return (
        <LemonBanner type="info" className={className} dismissKey={`signals-scout-banner-${scoutBannerMessage}`}>
            {scoutBannerMessage}
        </LemonBanner>
    )
}
