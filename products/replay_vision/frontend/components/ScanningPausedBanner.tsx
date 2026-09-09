import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { visionQuotaLogic } from '../logics/visionQuotaLogic'

/** Shown on the scanners list when the org's credits are used up, since the spend card that
 * carried this warning lives on the Usage tab under the home-redesign experiment. */
export function ScanningPausedBanner(): JSX.Element | null {
    const { displayQuota: quota, onFreePlan } = useValues(visionQuotaLogic)

    if (!quota?.exhausted) {
        return null
    }
    return (
        <LemonBanner type="warning" data-attr="vision-scanning-paused-banner">
            {onFreePlan ? (
                <>
                    Scanning is paused because your organization's free credits are used up.{' '}
                    <Link to={urls.organizationBilling([ProductKey.REPLAY_VISION])}>Add billing</Link> to keep scanning,
                    or check the <Link to={`${urls.replayVision()}?tab=usage`}>Usage tab</Link> for details.
                </>
            ) : (
                <>
                    Scanning is paused because your organization reached its monthly spend limit.{' '}
                    <Link to={urls.organizationBilling([ProductKey.REPLAY_VISION])}>Raise your billing limit</Link> to
                    resume scanning, or check the <Link to={`${urls.replayVision()}?tab=usage`}>Usage tab</Link> for
                    details.
                </>
            )}
        </LemonBanner>
    )
}
