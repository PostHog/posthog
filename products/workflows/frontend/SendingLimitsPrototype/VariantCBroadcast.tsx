// PROTOTYPE (branch prototype/sending-limits-ux): variant C, at broadcast time. The broadcast shows its
// delivery plan over days, a sample goes first, and the customer is told when the sample stops the
// send. Never merge.
import clsx from 'clsx'

import { IconCheck, IconClock, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { BroadcastShell } from './BroadcastShell'
import { PrototypeNote } from './PrototypeNote'
import { ReputationShell } from './ReputationShell'
import { BOUNCE_LIMIT, SendingState, SurfaceKey, sendDays } from './sendingLimitsPrototypeData'
import { SetupShell } from './SetupShell'

const fmt = humanFriendlyNumber
const pct = (rate: number): string => percentage(rate, 1, true)

function DeliveryPlan({ state }: { state: SendingState }): JSX.Element {
    const { broadcast } = state
    const max = Math.max(...broadcast.plan.map((day) => day.emails))
    return (
        <div className="flex items-end gap-2 h-24">
            {broadcast.plan
                .filter((day) => day.emails > 0)
                .map((day) => (
                    <div key={day.date} className="flex-1 flex flex-col items-center gap-1">
                        <span className="text-xs">{fmt(day.emails)}</span>
                        <div
                            className="w-full rounded-t bg-primary-3000"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ height: `${Math.max(8, (day.emails / max) * 56)}px` }}
                        />
                        <span className="text-xs text-secondary">{day.date}</span>
                    </div>
                ))}
        </div>
    )
}

type StepStatus = 'done' | 'active' | 'waiting' | 'stopped'

function TimelineStep({ status, title, detail }: { status: StepStatus; title: string; detail?: string }): JSX.Element {
    return (
        <div className="flex gap-3">
            <span
                className={clsx(
                    'mt-0.5 shrink-0',
                    status === 'done' && 'text-success',
                    status === 'active' && 'text-primary',
                    status === 'waiting' && 'text-secondary',
                    status === 'stopped' && 'text-danger'
                )}
            >
                {status === 'done' ? <IconCheck /> : status === 'stopped' ? <IconWarning /> : <IconClock />}
            </span>
            <span className="flex flex-col">
                <span
                    className={clsx(status === 'waiting' && 'text-secondary', status !== 'waiting' && 'font-semibold')}
                >
                    {title}
                </span>
                {detail && <span className="text-sm text-secondary">{detail}</span>}
            </span>
        </div>
    )
}

function SendTimeline({ state }: { state: SendingState }): JSX.Element {
    const { broadcast } = state
    const sample = broadcast.sample
    const steps: JSX.Element[] = []
    if (sample) {
        steps.push(
            <TimelineStep
                key="sample"
                status={sample.verdict === 'passed' ? 'done' : sample.verdict === 'stopped' ? 'stopped' : 'active'}
                title={`Sample: ${fmt(sample.size)} people first`}
                detail={
                    sample.verdict === 'checking'
                        ? `Sent. We wait until ${sample.heldUntil} and check how many bounce before sending the rest.`
                        : `${pct(sample.bounceRate ?? 0)} bounced. ${
                              sample.verdict === 'passed'
                                  ? 'Under the 2% limit, so the rest went ahead.'
                                  : 'Over the 2% limit.'
                          }`
                }
            />
        )
    }
    if (sample?.verdict !== 'stopped') {
        let cumulative = 0
        broadcast.plan
            .filter((day) => day.emails > 0)
            .forEach((day) => {
                cumulative += day.emails
                const done = cumulative <= broadcast.sentSoFar && sample?.verdict !== 'checking'
                steps.push(
                    <TimelineStep
                        key={day.date}
                        status={state.key === 'blocked' && !done ? 'stopped' : done ? 'done' : 'waiting'}
                        title={`${day.date}: ${fmt(day.emails)} emails`}
                        detail={
                            state.key === 'blocked' && !done
                                ? 'Paused with all email sending for this project'
                                : undefined
                        }
                    />
                )
            })
    }
    return <div className="flex flex-col gap-3">{steps}</div>
}

function RecipientsPlan({ state }: { state: SendingState }): JSX.Element {
    const { broadcast } = state
    if (state.key === 'blocked') {
        return (
            <LemonBanner type="error">
                Email sending is paused for this project, so this broadcast can't go out. <Link>See why</Link>.
            </LemonBanner>
        )
    }
    const days = sendDays(state)
    return (
        <div className="border rounded p-3 flex flex-col gap-3">
            <strong>{days > 1 ? `This goes out over ${days} days` : 'This goes out today'}</strong>
            {days > 1 && <DeliveryPlan state={state} />}
            {broadcast.sample && (
                <span className="text-sm">
                    {fmt(broadcast.sample.size)} people get it first. We wait an hour and check how many emails bounce.
                    If more than {pct(BOUNCE_LIMIT)} bounce, we stop and tell you before anyone else gets it.
                </span>
            )}
            {days > 1 && (
                <span className="text-xs text-secondary">
                    New senders send a little more each day, so inboxes learn to trust you.
                </span>
            )}
        </div>
    )
}

function SendsInProgress({ state }: { state: SendingState }): JSX.Element | null {
    const { broadcast } = state
    if (broadcast.sentSoFar >= broadcast.audience || state.key === 'new') {
        return null
    }
    const stopped = broadcast.sample?.verdict === 'stopped'
    return (
        <div className="border rounded p-4 bg-surface-primary flex flex-col gap-2">
            <h3 className="mb-0">Sends in progress</h3>
            <div className="flex items-center gap-4">
                <Link className="font-semibold w-56 shrink-0">{broadcast.name}</Link>
                <LemonProgress percent={(broadcast.sentSoFar / broadcast.audience) * 100} className="flex-1" />
                <span className="text-sm shrink-0">
                    {fmt(broadcast.sentSoFar)} of {fmt(broadcast.audience)}
                </span>
                <span className="text-sm text-secondary w-40 shrink-0">
                    {stopped || state.key === 'blocked'
                        ? 'Stopped'
                        : `Done by ${broadcast.plan[broadcast.plan.length - 1].date}`}
                </span>
            </div>
        </div>
    )
}

export function VariantCBroadcast({ surface, state }: { surface: SurfaceKey; state: SendingState }): JSX.Element {
    if (surface === 'setup') {
        return (
            <SetupShell domain={state.domain}>
                <div className="text-secondary text-sm text-center">
                    Large broadcasts from a new sender go out over a few days. Each broadcast shows its plan before you
                    launch it.
                </div>
            </SetupShell>
        )
    }
    if (surface === 'reputation') {
        return (
            <ReputationShell
                renderKey={`C-${state.key}`}
                state={state}
                allowance={() => <SendsInProgress state={state} />}
            />
        )
    }

    const { broadcast } = state
    const stopped = broadcast.sample?.verdict === 'stopped'
    const blocked = state.key === 'blocked'
    return (
        <BroadcastShell
            state={state}
            recipientsHint={<RecipientsPlan state={state} />}
            launchDisabledReason={blocked ? 'Email sending is paused for this project' : undefined}
            status={
                stopped
                    ? { label: 'Stopped after sample', type: 'danger' }
                    : blocked
                      ? { label: 'Paused', type: 'danger' }
                      : broadcast.sample?.verdict === 'checking'
                        ? { label: 'Checking sample', type: 'warning' }
                        : broadcast.sentSoFar < broadcast.audience
                          ? { label: `Sending over ${sendDays(state)} days`, type: 'primary' }
                          : { label: 'Sent', type: 'success' }
            }
            afterLaunch={
                <>
                    <div>
                        {fmt(broadcast.sentSoFar)} of {fmt(broadcast.audience)} people got it.
                    </div>
                    <LemonProgress percent={(broadcast.sentSoFar / broadcast.audience) * 100} />
                    {stopped && broadcast.sample && (
                        <LemonBanner type="error">
                            <div className="flex flex-col gap-2">
                                <span>
                                    We stopped this broadcast. {pct(broadcast.sample.bounceRate ?? 0)} of the first{' '}
                                    {fmt(broadcast.sample.size)} emails bounced, above the {pct(BOUNCE_LIMIT)} limit.
                                    The other {fmt(broadcast.audience - broadcast.sample.size)} people did not get it.
                                </span>
                                <span>
                                    Old or bought lists bounce. Remove the addresses that bounced, then send to the
                                    rest.
                                </span>
                                <div className="flex gap-2">
                                    <LemonButton type="secondary" size="small">
                                        See bounced addresses
                                    </LemonButton>
                                    <LemonButton type="secondary" size="small">
                                        Send to the rest
                                    </LemonButton>
                                </div>
                            </div>
                        </LemonBanner>
                    )}
                    <SendTimeline state={state} />
                    <PrototypeNote>
                        Agents create more broadcasts through the broadcasts-create MCP tool than people do in this
                        wizard, and they never see these hints. The build has to return the same delivery plan and
                        sample result from the tool.
                    </PrototypeNote>
                </>
            }
        />
    )
}
