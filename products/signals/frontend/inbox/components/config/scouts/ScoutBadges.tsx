import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type {
    ScoutDeprecationApi,
    ScoutOriginEnumApi,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'

import { ScoutGroupKey } from '../../../utils/scoutGroups'

/**
 * What a retirement PostHog announced for this scout says, in one tag. A scout that is on its way
 * out otherwise looks identical to a healthy one until the day it stops, and a retired one looks
 * like a scout somebody switched off. Nothing renders for a scout PostHog still ships, or for a
 * project's own edited copy of one, which keeps running.
 */
export function ScoutDeprecationBadge({ config }: { config: SignalScoutConfig }): JSX.Element | null {
    const deprecation: ScoutDeprecationApi | null | undefined = config.deprecation
    if (!deprecation) {
        return null
    }
    const sunsetOn = deprecation.sunset_at ? dayjs(deprecation.sunset_at).format('MMMM D, YYYY') : null
    // An announced retirement always carries a date, since a marker without one reads as retired.
    const announced = deprecation.phase === 'announced' && sunsetOn
    const label = announced ? `Retiring on ${sunsetOn}` : 'Retired'
    const headline = announced
        ? `PostHog is retiring this scout on ${sunsetOn}.`
        : sunsetOn
          ? `PostHog retired this scout on ${sunsetOn}.`
          : 'PostHog retired this scout.'
    return (
        <Tooltip title={`${headline} ${deprecation.reason}`.trim()}>
            <LemonTag type={announced ? 'caution' : 'danger'} size="small">
                {label}
            </LemonTag>
        </Tooltip>
    )
}

/**
 * Where the scout stands with the system writers that can pause it: the failure breaker
 * (`repeated_failures`) or the inactivity sweep (`no_output` / `ignored`), plus the sweep's
 * warning state (`pending_pause`). Without it a scout that has silently stopped looks the same
 * as one a person turned off. Nothing renders for a healthy scout or a user pause.
 */
export function ScoutLifecycleBadge({ config }: { config: SignalScoutConfig }): JSX.Element | null {
    if (config.pause_reason === 'retired') {
        // The retirement badge already says this, and with the reason.
        return null
    }
    if (config.status === 'paused_by_system') {
        if (config.pause_reason === 'repeated_failures') {
            return (
                <Tooltip
                    title={
                        <span>
                            This scout paused itself because its last few runs all failed. It retries about once a day
                            and resumes its normal schedule on the first successful run. Turn it on to resume it right
                            away.
                        </span>
                    }
                >
                    <LemonTag type="warning" size="small">
                        Paused
                    </LemonTag>
                </Tooltip>
            )
        }
        if (config.pause_reason === 'no_output' || config.pause_reason === 'ignored') {
            const pausedOn = config.status_changed_at
                ? `Paused on ${dayjs(config.status_changed_at).format('MMMM D, YYYY')}`
                : 'Paused'
            const why =
                config.pause_reason === 'ignored'
                    ? 'because nothing came of its recent reports'
                    : 'after two weeks without surfacing anything'
            return (
                <Tooltip title={`${pausedOn} ${why}. Switch it back on to resume it.`}>
                    <LemonTag type="warning" size="small">
                        Paused
                    </LemonTag>
                </Tooltip>
            )
        }
        return null
    }
    if (config.status === 'pending_pause') {
        // The two warnings say different things at a glance: `ignored` schedules a pause and can
        // apply to a scout that files plenty of reports, so labeling it "Quiet" would misread as
        // a benign watchdog.
        const ignored = config.pause_reason === 'ignored'
        const title = ignored
            ? "Nothing has come of this scout's recent reports, so it pauses in about a week unless that changes. Turn on 'Opt out of auto-pause' in its settings to leave it running."
            : "This scout hasn't surfaced anything in the last two weeks. It keeps running, but check that it's watching the right things. Turn on 'Opt out of auto-pause' in its settings if quiet is expected."
        return (
            <Tooltip title={title}>
                <LemonTag type="caution" size="small">
                    {ignored ? 'Pausing soon' : 'Quiet'}
                </LemonTag>
            </Tooltip>
        )
    }
    return null
}

/**
 * Why the inactivity sweep leaves this scout alone, in the terms the exemption came from: the role
 * PostHog ships it with, or a choice someone made on this project. Nothing renders for a scout the
 * sweep still judges. The role shows in any group, because it says what the scout is rather
 * than how its run window went.
 */
export function ScoutExemptionBadge({
    config,
    group,
}: {
    config: SignalScoutConfig
    group: ScoutGroupKey
}): JSX.Element | null {
    if (config.scout_role === 'operational') {
        return (
            <Tooltip title="Part of the self-driving system rather than this project's fleet. It checks whether shipped fixes held, so it keeps running and is never paused for being quiet.">
                <LemonTag type="muted" size="small">
                    Operational
                </LemonTag>
            </Tooltip>
        )
    }
    if (config.auto_pause_exempt && group === 'watching') {
        return (
            <Tooltip title="Exempt from auto-pause, because this scout is supposed to stay quiet">
                <LemonTag size="small">Quiet by design</LemonTag>
            </Tooltip>
        )
    }
    return null
}

/** Canonical (PostHog-maintained) vs Custom (team-authored) scout badge. */
export function ScoutOriginBadge({ origin }: { origin: ScoutOriginEnumApi }): JSX.Element {
    return (
        <Tooltip
            title={
                origin === 'canonical'
                    ? 'Part of the standard scout troop built and maintained by PostHog'
                    : 'A scout your team created as a skill in this project'
            }
        >
            <LemonTag type={origin === 'canonical' ? 'muted' : 'highlight'} size="small">
                {origin === 'canonical' ? 'Canonical' : 'Custom'}
            </LemonTag>
        </Tooltip>
    )
}

export function ScoutTagBadge({ tag }: { tag: string }): JSX.Element {
    return (
        <LemonTag type="highlight" size="small">
            {tag}
        </LemonTag>
    )
}

/** Where a scout stands right now, in one tag. Used on the scout page header and its settings modal. */
export function ScoutStatusTag({ config }: { config: SignalScoutConfig }): JSX.Element {
    if (config.pause_reason === 'retired') {
        return (
            <LemonTag type="danger" size="small">
                Retired
            </LemonTag>
        )
    }
    if (config.status === 'paused_by_system') {
        return (
            <LemonTag type="danger" size="small">
                Paused by the system
            </LemonTag>
        )
    }
    if (config.status === 'pending_pause') {
        return (
            <LemonTag type="warning" size="small">
                {config.pause_reason === 'ignored' ? 'Pausing soon' : 'Warned'}
            </LemonTag>
        )
    }
    if (!config.enabled) {
        return <LemonTag size="small">Off</LemonTag>
    }
    if (!config.emit) {
        return (
            <LemonTag type="option" size="small">
                Dry run
            </LemonTag>
        )
    }
    return (
        <LemonTag type="success" size="small">
            On patrol
        </LemonTag>
    )
}
