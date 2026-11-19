// PROTOTYPE (branch prototype/sending-limits-ux): variant B, explain it. A warm-up bar, the 7 days that
// decide every move, and a plain reason for each move up or down. Never merge.
import { IconCheck, IconTrending, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { IconTrendingDown } from 'lib/lemon-ui/icons'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { AskForMore } from './AskForMore'
import { BroadcastShell } from './BroadcastShell'
import { PlanAnswers } from './PlanAnswers'
import { PrototypeNote } from './PrototypeNote'
import { ReputationShell } from './ReputationShell'
import { BOUNCE_LIMIT, COMPLAINT_LIMIT, SendingState, SurfaceKey, sendDays } from './sendingLimitsPrototypeData'
import { sendPlan } from './sendPlan'
import { SetupShell } from './SetupShell'

const fmt = humanFriendlyNumber
const pct = (rate: number): string => percentage(rate, 2, true)

// Logarithmic, so 1,000 to 100,000 reads as a climb rather than a sliver.
function warmUpPercent(perDay: number, ceiling: number): number {
    if (perDay <= 0) {
        return 0
    }
    return Math.min(100, (Math.log10(perDay / 100) / Math.log10(ceiling / 100)) * 100)
}

const STATUS: Record<SendingState['key'], { label: string; type: LemonTagType }> = {
    new: { label: 'Starting out', type: 'muted' },
    warming: { label: 'Warming up', type: 'primary' },
    capped: { label: 'Warming up', type: 'primary' },
    'moved-down': { label: 'Slowed down', type: 'warning' },
    blocked: { label: 'Paused', type: 'danger' },
}

function NextStep({ state }: { state: SendingState }): JSX.Element {
    switch (state.key) {
        case 'new':
            return (
                <>
                    Send your first emails. Each day you send without many bounces or spam complaints raises your
                    allowance, up to {fmt(state.ceilingPerDay)} a day.
                </>
            )
        case 'moved-down':
            return (
                <>
                    Your allowance stays at {fmt(state.allowancePerDay)} until bounces over the last 7 days are back
                    under {pct(BOUNCE_LIMIT)}. If nothing else bounces, that happens on Dec 15.
                </>
            )
        case 'blocked':
            return <>Sending stays paused until support turns it back on. Fix the cause first.</>
        default:
            return (
                <>
                    If the last 7 days stay under {pct(BOUNCE_LIMIT)} bounces and {pct(COMPLAINT_LIMIT)} spam
                    complaints, tomorrow's allowance is {fmt(state.tomorrowIfClean)}.
                </>
            )
    }
}

function RateRow({ label, rate, limit }: { label: string; rate: number; limit: number }): JSX.Element {
    const over = rate > limit
    return (
        <div className="flex items-center justify-between gap-4 text-sm">
            <span>{label}</span>
            <span className="flex items-center gap-2">
                <span className={over ? 'text-danger font-semibold' : undefined}>{pct(rate)}</span>
                <span className="text-secondary">limit {pct(limit)}</span>
                {over ? <IconWarning className="text-danger" /> : <IconCheck className="text-success" />}
            </span>
        </div>
    )
}

function WarmUpCard({ state }: { state: SendingState }): JSX.Element {
    const status = STATUS[state.key]
    return (
        <div
            className="border rounded p-4 bg-surface-primary flex flex-col gap-4"
            data-attr="workflows-sending-warm-up"
        >
            <div className="flex items-center gap-2">
                <h3 className="mb-0">Sending warm-up</h3>
                <LemonTag type={status.type}>{status.label}</LemonTag>
            </div>
            <div className="flex flex-wrap gap-8">
                <div className="flex-1 min-w-64 flex flex-col gap-1">
                    <span className="text-secondary text-xs">Today's allowance</span>
                    <span className="text-2xl font-semibold">
                        {state.key === 'blocked' ? 'Paused' : `${fmt(state.allowancePerDay)} emails a day`}
                    </span>
                    <LemonProgress percent={warmUpPercent(state.allowancePerDay, state.ceilingPerDay)} />
                    <span className="text-xs text-secondary">
                        Warm-up ends at {fmt(state.ceilingPerDay)} a day. Emails over the allowance wait and go out the
                        next day. Nothing is dropped.
                    </span>
                    {state.queued > 0 && state.key !== 'blocked' && (
                        <span className="text-sm">
                            {fmt(state.queued)} emails are waiting and go out over the next {sendDays(state) - 1} days.
                        </span>
                    )}
                </div>
                <div className="flex-1 min-w-64 flex flex-col gap-2">
                    <span className="text-secondary text-xs">The last 7 days decide every move</span>
                    {state.rates7d.sent > 0 ? (
                        <>
                            <RateRow label="Bounces" rate={state.rates7d.bounce} limit={BOUNCE_LIMIT} />
                            <RateRow label="Spam complaints" rate={state.rates7d.complaint} limit={COMPLAINT_LIMIT} />
                            <span className="text-xs text-secondary">
                                {fmt(state.rates7d.sent)} emails in the last 7 days. The rates further down this page
                                cover 30 days.
                            </span>
                        </>
                    ) : (
                        <span className="text-sm text-secondary">No emails sent yet.</span>
                    )}
                </div>
            </div>
            <div className="text-sm">
                <strong>What happens next: </strong>
                <NextStep state={state} />
                {state.key !== 'blocked' && (
                    <>
                        {' '}
                        Need more sooner?{' '}
                        <Link data-attr="workflows-request-sending-tier-increase">Request a higher allowance</Link>.
                    </>
                )}
            </div>
            <PrototypeNote>
                The "Request a higher allowance" button stays (flag workflows-sending-tier-requests), now next to the
                reason it is needed. It asks staff for a higher limit, as today.
            </PrototypeNote>
            <div className="flex flex-col gap-2">
                <span className="text-secondary text-xs">Why your allowance changed</span>
                {[...state.moves].reverse().map((move) => (
                    <div key={move.date + move.to} className="flex gap-3 text-sm">
                        <span className="w-14 shrink-0 text-secondary">{move.date}</span>
                        <span className="shrink-0">
                            {move.direction === 'down' ? (
                                <IconTrendingDown className="text-danger" />
                            ) : (
                                <IconTrending className="text-success" />
                            )}
                        </span>
                        <span>
                            <strong>
                                {move.direction === 'start'
                                    ? `Started at ${fmt(move.to)} a day`
                                    : move.to === 0
                                      ? 'Paused'
                                      : `${move.direction === 'up' ? 'Up' : 'Down'} to ${fmt(move.to)} a day`}
                                .
                            </strong>{' '}
                            {move.reason}
                        </span>
                    </div>
                ))}
            </div>
        </div>
    )
}

function BlockedBanner({ state }: { state: SendingState }): JSX.Element {
    return (
        <LemonBanner type="error">
            <div className="flex flex-col gap-1">
                <strong>Email sending is paused.</strong>
                <span>{state.blockedReason}</span>
                <span>
                    To send again, remove people who did not sign up for your emails, add an unsubscribe link, then
                    contact support.
                </span>
            </div>
        </LemonBanner>
    )
}

export function VariantBExplain({ surface, state }: { surface: SurfaceKey; state: SendingState }): JSX.Element {
    if (surface === 'setup') {
        return (
            <SetupShell domain={state.domain}>
                <div className="border rounded p-4 flex flex-col gap-1">
                    <strong>You start at 1,000 emails a day</strong>
                    <span className="text-secondary">
                        Inboxes trust new senders slowly. Each day you send without many bounces or spam complaints
                        raises your allowance, up to {fmt(state.ceilingPerDay)} a day. Follow it on the{' '}
                        <Link>Reputation page</Link>.
                    </span>
                    <span className="text-secondary">
                        <AskForMore />
                    </span>
                </div>
            </SetupShell>
        )
    }
    if (surface === 'reputation') {
        return (
            <ReputationShell
                renderKey={`B-${state.key}`}
                state={state}
                allowance={() => <WarmUpCard state={state} />}
                banners={() => (state.key === 'blocked' ? <BlockedBanner state={state} /> : null)}
            />
        )
    }

    const { broadcast } = state
    const blocked = state.key === 'blocked'
    const plan = sendPlan(state)
    const stopped = broadcast.sample?.verdict === 'stopped'
    return (
        <BroadcastShell
            state={state}
            launchDisabledReason={blocked ? 'Email sending is paused for this project' : undefined}
            recipientsHint={
                <PlanAnswers
                    plan={plan}
                    paused={blocked ? 'sending is paused' : undefined}
                    why={
                        <>
                            {blocked
                                ? state.blockedReason
                                : `Your allowance is ${fmt(state.allowancePerDay)} emails a day. ${
                                      plan.whyChanged ??
                                      'Every new sender starts here, and it grows each day you send without many bounces or spam complaints.'
                                  }`}{' '}
                            <Link>{blocked ? 'See what to fix' : 'See your warm-up'}</Link>.
                        </>
                    }
                />
            }
            status={
                blocked || stopped
                    ? { label: blocked ? 'Paused' : 'Stopped', type: 'danger' }
                    : broadcast.sentSoFar < broadcast.audience
                      ? { label: 'Sending', type: 'primary' }
                      : { label: 'Sent', type: 'success' }
            }
            afterLaunch={
                <>
                    <div>
                        {fmt(broadcast.sentSoFar)} of {fmt(broadcast.audience)} people got it.
                    </div>
                    <LemonProgress percent={(broadcast.sentSoFar / broadcast.audience) * 100} />
                    {state.key === 'moved-down' && (
                        <LemonBanner type="warning">
                            3.4% of the emails sent in the last 7 days bounced, above the 2% limit. Most came from this
                            broadcast, so we stopped it and halved your allowance to {fmt(state.allowancePerDay)} a day.{' '}
                            <Link>See your warm-up</Link>.
                        </LemonBanner>
                    )}
                    {blocked && <BlockedBanner state={state} />}
                    {!blocked && !stopped && broadcast.sentSoFar < broadcast.audience && (
                        <span className="text-sm text-secondary">
                            Everyone gets it by {plan.finish}, within your daily allowance.{' '}
                            <Link>See your warm-up</Link>.
                        </span>
                    )}
                </>
            }
        />
    )
}
