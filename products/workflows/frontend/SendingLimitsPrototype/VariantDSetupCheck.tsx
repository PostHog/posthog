// PROTOTYPE (branch prototype/sending-limits-ux): variant D, check at sender setup. A domain health
// check runs when the sender is verified and sets the starting allowance. It runs again daily, which
// is how a blocklist listing pauses a sender later. Never merge.
import { IconCheck, IconRefresh, IconWarning, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { BroadcastShell } from './BroadcastShell'
import { ReputationShell } from './ReputationShell'
import {
    DOMAIN_CHECKS,
    DomainCheck,
    DomainProfileKey,
    SendingState,
    SurfaceKey,
    sendDays,
} from './sendingLimitsPrototypeData'
import { SetupShell } from './SetupShell'

const fmt = humanFriendlyNumber

function Signal({ signal }: { signal: DomainCheck['signals'][number] }): JSX.Element {
    return (
        <div className="flex items-center gap-3 text-sm">
            <span className="shrink-0">
                {signal.ok === true ? (
                    <IconCheck className="text-success" />
                ) : signal.ok === 'warn' ? (
                    <IconWarning className="text-warning" />
                ) : (
                    <IconX className="text-danger" />
                )}
            </span>
            <span className="w-40 shrink-0 font-semibold">{signal.label}</span>
            <span className="text-secondary">{signal.detail}</span>
        </div>
    )
}

function DomainCheckCard({ check, checkedOn }: { check: DomainCheck; checkedOn: string }): JSX.Element {
    return (
        <div
            className="border rounded p-4 bg-surface-primary flex flex-col gap-3"
            data-attr="email-domain-health-check"
        >
            <div className="flex items-center justify-between">
                <h3 className="m-0">Domain check</h3>
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
                    {check.startPerDay === null ? "Can't send yet" : `${fmt(check.startPerDay)} emails a day`}
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
    const check =
        state.key === 'blocked' ? { ...DOMAIN_CHECKS.listed, domain: state.domain } : DOMAIN_CHECKS[domainProfile]
    const domain = state.key === 'new' ? check.domain : state.domain
    const startPerDay = check.startPerDay ?? 0
    const todayPerDay = state.key === 'new' ? startPerDay : Math.max(state.allowancePerDay, startPerDay)
    const checkedOn =
        state.key === 'blocked' ? 'Dec 9, in the daily re-check' : state.key === 'new' ? 'just now' : 'Dec 3'

    if (surface === 'setup') {
        const listed = check.startPerDay === null
        return (
            <SetupShell
                domain={domain}
                tone={listed ? 'warning' : 'success'}
                title={listed ? <>{domain} can't send yet</> : undefined}
                lead={
                    listed
                        ? 'The settings are in place, but the domain check found a problem.'
                        : `All 3 settings are in place. You can send up to ${fmt(startPerDay)} emails a day to start.`
                }
            >
                {state.key === 'new' && <ProfilePicker value={domainProfile} onChange={setDomainProfile} />}
                <DomainCheckCard check={{ ...check, domain }} checkedOn={checkedOn} />
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
    const blocked = state.key === 'blocked'
    const stopped = broadcast.sample?.verdict === 'stopped'
    const days = state.key === 'new' ? Math.ceil(broadcast.audience / Math.max(startPerDay, 1)) : sendDays(state)
    return (
        <BroadcastShell
            state={state}
            launchDisabledReason={blocked ? 'Email sending is paused for this project' : undefined}
            recipientsHint={
                blocked ? (
                    <div className="text-danger text-xs">
                        Email sending is paused: {state.domain} is on a spam blocklist.{' '}
                        <Link>See the domain check</Link>.
                    </div>
                ) : broadcast.audience > todayPerDay ? (
                    <div className="text-xs">
                        You can send {fmt(todayPerDay)} emails a day right now, so this goes out over about {days} days.
                    </div>
                ) : null
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
                    {stopped && (
                        <LemonBanner type="error">
                            We stopped this broadcast because too many emails bounced. Remove addresses that bounced,
                            then send it again.
                        </LemonBanner>
                    )}
                    {blocked && (
                        <LemonBanner type="error">
                            Paused: {state.domain} showed up on a spam blocklist on Dec 9.{' '}
                            <Link>See the domain check</Link>.
                        </LemonBanner>
                    )}
                    {!blocked && !stopped && broadcast.sentSoFar < broadcast.audience && (
                        <span className="text-sm text-secondary">The rest goes out over the next {days - 1} days.</span>
                    )}
                </>
            }
        />
    )
}
