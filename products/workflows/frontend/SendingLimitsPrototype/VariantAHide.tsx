// PROTOTYPE (branch prototype/sending-limits-ux): variant A, hide it. No limits anywhere; one line
// appears only when a send is held back. Never merge.
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { BroadcastShell } from './BroadcastShell'
import { ReputationShell } from './ReputationShell'
import { SendingState, SurfaceKey } from './sendingLimitsPrototypeData'
import { SetupShell } from './SetupShell'

const WARM_UP_LINE =
    "We warm up your domain so you don't get spam complaints, so the rest goes out over the next few days."

export function VariantAHide({ surface, state }: { surface: SurfaceKey; state: SendingState }): JSX.Element {
    if (surface === 'setup') {
        return <SetupShell domain={state.domain} />
    }
    if (surface === 'reputation') {
        // No allowance card at all. The real page keeps its rates, findings and paused banner.
        return <ReputationShell renderKey={`A-${state.key}`} state={state} allowance={() => null} />
    }

    const { broadcast } = state
    const blocked = state.key === 'blocked'
    const stopped = broadcast.sample?.verdict === 'stopped'
    const held = !blocked && !stopped && broadcast.sentSoFar < broadcast.audience
    const percent = (broadcast.sentSoFar / broadcast.audience) * 100

    return (
        <BroadcastShell
            state={state}
            launchDisabledReason={blocked ? 'Email sending is paused for this project' : undefined}
            recipientsHint={
                blocked ? (
                    <div className="text-danger text-xs">
                        Email sending is paused for this project. See the Reputation page for what to fix.
                    </div>
                ) : null
            }
            status={
                blocked
                    ? { label: 'Paused', type: 'danger' }
                    : stopped
                      ? { label: 'Stopped', type: 'danger' }
                      : held
                        ? { label: 'Sending', type: 'primary' }
                        : { label: 'Sent', type: 'success' }
            }
            afterLaunch={
                <>
                    <div>
                        {humanFriendlyNumber(broadcast.sentSoFar)} of {humanFriendlyNumber(broadcast.audience)} people
                        got it.
                    </div>
                    <LemonProgress percent={percent} />
                    {held && <div className="text-secondary text-sm">{WARM_UP_LINE}</div>}
                    {stopped && (
                        <LemonBanner type="error">
                            We stopped this broadcast because too many emails bounced. Remove addresses that bounced,
                            then send it again.
                        </LemonBanner>
                    )}
                    {blocked && (
                        <LemonBanner type="error">
                            Email sending is paused for this project, so the other{' '}
                            {humanFriendlyNumber(broadcast.audience - broadcast.sentSoFar)} people did not get it. See
                            the Reputation page for what to fix.
                        </LemonBanner>
                    )}
                </>
            }
        />
    )
}
