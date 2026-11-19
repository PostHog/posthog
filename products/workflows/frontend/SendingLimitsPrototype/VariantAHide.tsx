// PROTOTYPE (branch prototype/sending-limits-ux): variant A, hide it. No allowance, tiers or warm-up
// anywhere. The recipients step still says who gets it, when it finishes and why, in plain words. Never merge.
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AskForMore } from './AskForMore'
import { BroadcastShell } from './BroadcastShell'
import { PlanAnswers } from './PlanAnswers'
import { PrototypeNote } from './PrototypeNote'
import { ReputationShell } from './ReputationShell'
import { AllowanceMove, SendingState, SurfaceKey } from './sendingLimitsPrototypeData'
import { sendPlan } from './sendPlan'
import { SetupShell } from './SetupShell'

const NEW_SENDER = 'Inboxes trust a new sender slowly, so large sends go out over a few days.'

// No allowance numbers in this variant, so a change reads as sending speeding up or slowing down.
function plainWhy(change: AllowanceMove | null): string {
    if (!change) {
        return NEW_SENDER
    }
    return change.direction === 'down'
        ? `On ${change.date} sending slowed down. ${change.reason}`
        : `${NEW_SENDER} On ${change.date} it sped up. ${change.reason}`
}

export function VariantAHide({ surface, state }: { surface: SurfaceKey; state: SendingState }): JSX.Element {
    if (surface === 'setup') {
        return (
            <SetupShell domain={state.domain}>
                <div className="text-secondary text-sm text-center flex flex-col gap-1">
                    <span>
                        Your first day sends to up to 1,000 people, and more each day after that. Each broadcast says
                        who gets it and when it finishes before you launch it.
                    </span>
                    <AskForMore />
                </div>
            </SetupShell>
        )
    }
    if (surface === 'reputation') {
        // No allowance card at all. The real page keeps its rates, findings and paused banner.
        return (
            <ReputationShell
                renderKey={`A-${state.key}`}
                state={state}
                allowance={() => (
                    <PrototypeNote>
                        The allowance card is gone. The "Request a higher allowance" link moves to sender setup and the
                        broadcast recipients step, where people plan a send (flag workflows-sending-tier-requests). The
                        workflows-reputation-get MCP tool keeps returning the allowance for agents.
                    </PrototypeNote>
                )}
            />
        )
    }

    const { broadcast } = state
    const blocked = state.key === 'blocked'
    const stopped = broadcast.sample?.verdict === 'stopped'
    const held = !blocked && !stopped && broadcast.sentSoFar < broadcast.audience
    const percent = (broadcast.sentSoFar / broadcast.audience) * 100
    const plan = sendPlan(state)
    const why = blocked ? state.blockedReason : plainWhy(plan.latestChange)

    return (
        <BroadcastShell
            state={state}
            launchDisabledReason={blocked ? 'Email sending is paused for this project' : undefined}
            recipientsHint={<PlanAnswers plan={plan} why={why} paused={blocked ? 'sending is paused' : undefined} />}
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
                    {held && (
                        <div className="text-secondary text-sm">
                            Everyone gets it by {plan.finish}. {plainWhy(plan.latestChange)}
                        </div>
                    )}
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
