import { useValues } from 'kea'

import { Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'
import { useSelfDrivingRunInFlight } from 'scenes/onboarding/shared/wizard-sync/hooks'
import { urls } from 'scenes/urls'

import { scoutFleetLogic } from '../logics/scoutFleetLogic'
import { signalSourcesLogic } from '../signalSourcesLogic'

/**
 * Why an inbox surface is empty, in whichever of the two phases it's in. One component rather than
 * two self-gating siblings so the phases stay mutually exclusive by construction, and so the
 * run-in-flight check happens once per surface.
 *
 * The post-setup half answers the question that actually gets asked — is anything running? — with
 * counts and a last-sweep time rather than reassurance, since a number can be checked. It stays
 * quiet when nothing is configured, where an empty inbox is the honest answer.
 */
export function SelfDrivingEmptyStateHint({ installingMessage }: { installingMessage: string }): JSX.Element | null {
    const runInFlight = useSelfDrivingRunInFlight()
    const { enabledCount, lastRunAt } = useValues(scoutFleetLogic)
    const { enabledSourcesCount } = useValues(signalSourcesLogic)

    if (runInFlight) {
        return (
            <span className="inline-flex items-center gap-1.5 text-xs text-tertiary mt-1">
                <Spinner className="text-sm" />
                {installingMessage}
            </span>
        )
    }

    if (enabledCount === 0 && enabledSourcesCount === 0) {
        return null
    }

    const watching = [
        enabledCount > 0 ? pluralize(enabledCount, 'scout') : null,
        enabledSourcesCount > 0 ? pluralize(enabledSourcesCount, 'signal source') : null,
    ]
        .filter(Boolean)
        .join(' and ')

    return (
        <div className="flex flex-col items-center gap-1 text-xs text-tertiary mt-2">
            <span>
                {watching} watching this project.{' '}
                {lastRunAt ? (
                    <>
                        Last swept <TZLabel time={lastRunAt} showPopover={false} />.
                    </>
                ) : (
                    'Scouts sweep on a schedule, so the first findings take a few hours.'
                )}
            </span>
            <Link to={urls.inbox('config')} className="text-xs">
                Check what's set up
            </Link>
        </div>
    )
}
