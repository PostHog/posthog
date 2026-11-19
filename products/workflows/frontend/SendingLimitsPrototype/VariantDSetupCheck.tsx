// PROTOTYPE (branch prototype/sending-limits-ux): variant D, check at sender setup. A domain health
// check runs when the sender is verified and sets the starting allowance. It runs again daily, which
// is how a blocklist listing pauses a sender later. Never merge.
import { IconCheck, IconRefresh, IconWarning, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AskForMore } from './AskForMore'
import { BroadcastShell } from './BroadcastShell'
import { PlanAnswers } from './PlanAnswers'
import { PrototypeNote } from './PrototypeNote'
import { ReputationShell } from './ReputationShell'
import {
    DOMAIN_CHECKS,
    DomainBand,
    DomainCheck,
    DomainProfileKey,
    SendingState,
    SurfaceKey,
} from './sendingLimitsPrototypeData'
import { flatPlan, sendPlan } from './sendPlan'
import { SetupShell } from './SetupShell'

const fmt = humanFriendlyNumber

const BAND_TAG: Record<DomainBand, LemonTagType> = { Hold: 'danger', Starter: 'muted', Established: 'success' }

function Signal({ signal }: { signal: DomainCheck['signals'][number] }): JSX.Element {
    return (
        <div className="flex items-center gap-3 text-sm">
            <span className="shrink-0">
                {signal.ok === true ? (
                    <IconCheck className="text-success" />
                ) : signal.ok === 'warn' ? (
                    <IconWarning className="text-warning" />
                ) : signal.ok === 'unknown' ? (
                    <IconWarning className="text-secondary" />
                ) : (
                    <IconX className="text-danger" />
                )}
            </span>
            <span className="w-40 shrink-0 font-semibold">{signal.label}</span>
            <span className="text-secondary">{signal.detail}</span>
            {/* Spamhaus and similar lists charge for commercial lookups. */}
            {signal.label === 'Blocklists' && (
                <LemonTag type="muted" size="small">
                    Needs a paid feed
                </LemonTag>
            )}
        </div>
    )
}

export function DomainCheckCard({ check, checkedOn }: { check: DomainCheck; checkedOn: string }): JSX.Element {
    return (
        <div
            className="border rounded p-4 bg-surface-primary flex flex-col gap-3"
            data-attr="email-domain-health-check"
        >
            <div className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                    <h3 className="m-0">Domain check</h3>
                    <LemonTag type={check.source === 'paid plan' ? 'success' : BAND_TAG[check.band]}>
                        {check.source === 'paid plan' ? 'Paid plan' : check.band}
                    </LemonTag>
                </span>
                <span className="text-xs text-secondary">Checked {checkedOn}</span>
            </div>
            <div className="flex flex-col gap-2">
                {check.signals.map((signal) => (
                    <Signal key={signal.label} signal={signal} />
                ))}
            </div>
            <div className="border-t pt-3 flex flex-col gap-1">
                <span className="text-xs text-secondary">Starting allowance</span>
                <span className="text-xl font-semibold">
                    {check.startPerDay === null
                        ? 'On hold'
                        : `${check.startPerDay > 1000 ? 'Up to ' : ''}${fmt(check.startPerDay)} emails a day`}
                </span>
                <span className="text-xs text-secondary">
                    {check.source === 'paid plan'
                        ? 'Set by your paid plan. Paid plans start at tier 3.'
                        : `Set by the domain check: ${check.band}.`}
                </span>
                <span className="text-sm">{check.verdict}</span>
            </div>
            {check.startPerDay === null && (
                <div>
                    <LemonButton type="secondary" icon={<IconRefresh />}>
                        Check again
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

function ProfilePicker({
    value,
    onChange,
}: {
    value: DomainProfileKey
    onChange: (value: DomainProfileKey) => void
}): JSX.Element {
    return (
        <div className="border border-dashed rounded p-2 flex items-center gap-2 text-xs">
            <span className="text-secondary">Prototype: try another domain</span>
            <LemonSegmentedButton
                size="xsmall"
                value={value}
                onChange={onChange}
                options={Object.values(DOMAIN_CHECKS).map((check) => ({ value: check.key, label: check.label }))}
            />
        </div>
    )
}

interface VariantDProps {
    surface: SurfaceKey
    state: SendingState
    domainProfile: DomainProfileKey
    setDomainProfile: (value: DomainProfileKey) => void
}

export function VariantDSetupCheck({ surface, state, domainProfile, setDomainProfile }: VariantDProps): JSX.Element {
    // A blocked sender in this variant is one the daily re-check found on a blocklist.
    // Only the new-sender state lets you pick a domain. Later states assume a domain that was not on hold.
    const picked = DOMAIN_CHECKS[domainProfile]
    const check =
        state.key === 'blocked'
            ? { ...DOMAIN_CHECKS.listed, domain: state.domain }
            : state.key === 'new' || picked.band !== 'Hold'
              ? picked
              : DOMAIN_CHECKS.starter
    const onHold = check.startPerDay === null
    const domain = state.key === 'new' ? check.domain : state.domain
    const startPerDay = check.startPerDay ?? 0
    const todayPerDay = state.key === 'new' ? startPerDay : Math.max(state.allowancePerDay, startPerDay)
    const checkedOn =
        state.key === 'blocked' ? 'Dec 9, in the daily re-check' : state.key === 'new' ? 'just now' : 'Dec 3'

    if (surface === 'setup') {
        const listed = onHold
        return (
            <SetupShell
                domain={domain}
                tone={listed ? 'warning' : 'success'}
                title={listed ? <>{domain} is on hold</> : undefined}
                lead={
                    listed
                        ? 'The settings are in place, but the domain check put sending on hold.'
                        : `All 3 settings are in place. You can send up to ${fmt(startPerDay)} emails a day to start.`
                }
            >
                {state.key === 'new' && <ProfilePicker value={domainProfile} onChange={setDomainProfile} />}
                <DomainCheckCard check={{ ...check, domain }} checkedOn={checkedOn} />
                {!listed && (
                    <div className="text-secondary text-sm text-center">
                        <AskForMore />
                    </div>
                )}
                <PrototypeNote>
                    The check sits on the ready step, next to today's sending tips (below). Paying organizations start
                    at tier 3, 10,000 a day, by the rule from PostHog/posthog#124520; this variant only shows it.
                    Everyone else gets a band from the domain check: domain age, MX records, other senders in SPF and
                    blocklists sort it into Hold, Starter or Established. DMARC strength is not an input. The blocklist
                    lookup needs a paid feed. A failed lookup lands in Starter, and setup never fails on it.
                </PrototypeNote>
            </SetupShell>
        )
    }

    if (surface === 'reputation') {
        return (
            <ReputationShell
                renderKey={`D-${state.key}-${domainProfile}`}
                state={state}
                banners={() =>
                    state.key === 'blocked' ? (
                        <LemonBanner type="error">
                            Email sending is paused. On Dec 9 {state.domain} showed up on the Spamhaus domain blocklist.
                            Ask Spamhaus to delist it, then check the domain again.
                        </LemonBanner>
                    ) : null
                }
                allowance={() =>
                    state.key === 'blocked' ? (
                        <DomainCheckCard check={check} checkedOn={checkedOn} />
                    ) : (
                        <div className="border rounded p-4 bg-surface-primary flex flex-wrap gap-8">
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-secondary">Today you can send</span>
                                <span className="text-xl font-semibold">{fmt(todayPerDay)} emails a day</span>
                                <span className="text-xs text-secondary">
                                    Started at {fmt(startPerDay)} after the domain check on {checkedOn}. It grows as you
                                    send without many bounces or spam complaints.
                                </span>
                            </div>
                            <div className="flex flex-col gap-1 text-sm">
                                <span className="text-xs text-secondary">Domain check</span>
                                {check.signals.map((signal) => (
                                    <span key={signal.label} className="flex items-center gap-2">
                                        {signal.ok === true ? (
                                            <IconCheck className="text-success" />
                                        ) : (
                                            <IconWarning className="text-warning" />
                                        )}
                                        {signal.detail}
                                    </span>
                                ))}
                                <Link>Check again</Link>
                            </div>
                        </div>
                    )
                }
            />
        )
    }

    const { broadcast } = state
    const blocked = state.key === 'blocked' || onHold
    const stopped = broadcast.sample?.verdict === 'stopped'
    // Above the Starter band the first send is a sample, because an aged domain can be bought.
    const sampleFirst = state.key === 'new' && startPerDay > 1000
    const sent = sampleFirst ? Math.round(broadcast.audience * 0.05) : broadcast.sentSoFar
    const newOnHold = onHold && state.key === 'new'
    const plan = sendPlan(state, state.key === 'new' ? flatPlan(broadcast.audience, startPerDay) : undefined)
    return (
        <BroadcastShell
            state={state}
            launchDisabledReason={
                blocked
                    ? onHold && state.key === 'new'
                        ? 'Sending from this domain is on hold'
                        : 'Email sending is paused for this project'
                    : undefined
            }
            recipientsHint={
                <>
                    {sampleFirst && (
                        <div className="text-sm">
                            This is your first broadcast, so {fmt(Math.round(broadcast.audience * 0.05))} people get it
                            first. We wait an hour and check how many emails bounce, then send to the rest today.
                        </div>
                    )}
                    <PlanAnswers
                        plan={plan}
                        paused={blocked ? (newOnHold ? 'this domain is on hold' : 'sending is paused') : undefined}
                        why={
                            <>
                                {state.key === 'blocked'
                                    ? `On Dec 9 ${state.domain} showed up on the Spamhaus domain blocklist, so sending is paused.`
                                    : newOnHold
                                      ? check.verdict
                                      : (plan.whyChanged ??
                                        `The domain check set your start at ${fmt(startPerDay)} emails a day. It grows each day you send without many bounces or spam complaints.`)}{' '}
                                <Link>See the domain check</Link>.
                            </>
                        }
                    />
                </>
            }
            status={
                blocked || stopped
                    ? { label: blocked ? 'Paused' : 'Stopped', type: 'danger' }
                    : sampleFirst
                      ? { label: 'Checking sample', type: 'warning' }
                      : broadcast.sentSoFar < broadcast.audience
                        ? { label: 'Sending', type: 'primary' }
                        : { label: 'Sent', type: 'success' }
            }
            afterLaunch={
                <>
                    <div>
                        {fmt(sent)} of {fmt(broadcast.audience)} people got it.
                    </div>
                    <LemonProgress percent={(sent / broadcast.audience) * 100} />
                    {stopped && (
                        <LemonBanner type="error">
                            We stopped this broadcast because too many emails bounced. Remove addresses that bounced,
                            then send it again.
                        </LemonBanner>
                    )}
                    {blocked && (
                        <LemonBanner type="error">
                            {onHold && state.key === 'new'
                                ? `On hold: ${check.verdict}`
                                : `Paused: ${state.domain} showed up on a spam blocklist on Dec 9.`}{' '}
                            <Link>See the domain check</Link>.
                        </LemonBanner>
                    )}
                    {sampleFirst && (
                        <span className="text-sm">
                            {fmt(Math.round(broadcast.audience * 0.05))} people got it as a sample. We check bounces
                            until 15:40, then send to the other {fmt(Math.round(broadcast.audience * 0.95))}.
                        </span>
                    )}
                    {!blocked && !stopped && !sampleFirst && broadcast.sentSoFar < broadcast.audience && (
                        <span className="text-sm text-secondary">Everyone gets it by {plan.finish}.</span>
                    )}
                </>
            }
        />
    )
}
