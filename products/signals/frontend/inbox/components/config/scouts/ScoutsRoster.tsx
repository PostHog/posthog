import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import { IconCompass, IconSparkles } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonMenu,
    LemonSegmentedButton,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { captureScoutFleetViewed } from '../../../inboxAnalytics'
import type { ScoutChatType } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import {
    nextRunAt,
    SCOUT_GROUP_HINT,
    SCOUT_GROUP_LABEL,
    ScoutGroupBucket,
    ScoutGroupKey,
    scoutCadenceLabel,
    scoutSubtitle,
} from '../../../utils/scoutGroups'
import { prettifyScoutSkillName, SCOUT_RUNS_PER_SCOUT_LABEL, ScoutRollup } from '../../../utils/scoutRunsWindow'
import { ScoutEnabledSwitch } from './ScoutConfigControls'
import { ScoutCreateButton } from './ScoutCreateButton'
import { ScoutHelperSkillLinks } from './ScoutHelperSkillLinks'
import { ScoutRunBoxes } from './ScoutRunBoxes'
import { ScoutStatusDot } from './ScoutStatusDot'
import { ScoutSuggestButton } from './ScoutSuggestButton'
import { ScoutTagsFilter } from './ScoutTagsFilter'

/**
 * The scout roster: one grouped table over the whole troop, ordered so the scouts that need a
 * decision sit above the ones that don't. Replaces the card list that used to live in the Scout
 * troop modal — the fleet outgrew a 760px portal, and a modal can't host the scout pages it links to.
 */
export function ScoutsRoster(): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading, enabledCount, customScoutCount } = useValues(scoutFleetLogic)
    const { loadScoutConfigs, startRunsPolling, stopRunsPolling } = useActions(scoutFleetLogic)

    useEffect(() => {
        startRunsPolling()
        return () => stopRunsPolling()
    }, [startRunsPolling, stopRunsPolling])

    // Roster shape once per opening, the first time the fleet resolves. A failed load stays `null`
    // and reports nothing — an unreachable scout API isn't an empty troop.
    const fleetViewedFiredRef = useRef(false)
    useEffect(() => {
        if (scoutConfigs === null || fleetViewedFiredRef.current) {
            return
        }
        fleetViewedFiredRef.current = true
        captureScoutFleetViewed({
            scoutCount: scoutConfigs.length,
            enabledCount,
            customCount: customScoutCount,
            dryRunCount: scoutConfigs.filter((config) => !config.emit).length,
        })
    }, [scoutConfigs, enabledCount, customScoutCount])

    if (scoutConfigsLoading && scoutConfigs === null) {
        return (
            <div className="flex flex-col gap-2 p-6">
                <LemonSkeleton className="h-8 w-full rounded" />
                <LemonSkeleton className="h-8 w-full rounded" />
                <LemonSkeleton className="h-8 w-full rounded" />
            </div>
        )
    }

    // A failed request must not masquerade as an empty troop – a missing scope or
    // regional rollout gap would otherwise be indistinguishable from "no scouts yet".
    if (scoutConfigs === null) {
        return (
            <div className="m-6 flex items-center gap-3 rounded border border-danger bg-danger-highlight px-4 py-3.5">
                <span className="flex-1 text-xs text-danger">
                    Couldn't load the scout roster. The scout API may be unavailable or this project may not be enrolled
                    yet.
                </span>
                <LemonButton type="secondary" size="small" status="danger" onClick={() => loadScoutConfigs()}>
                    Retry
                </LemonButton>
            </div>
        )
    }

    if (scoutConfigs.length === 0) {
        return <ScoutsEmptyState />
    }

    return (
        <div className="flex flex-col">
            <RosterHeader />
            <RosterGroups />
            <div className="flex flex-col gap-1 px-6 py-4">
                <span className="text-xs text-muted">
                    Run counts cover each scout's {SCOUT_RUNS_PER_SCOUT_LABEL}, so scouts on different schedules stay
                    comparable. New scouts are created as <span className="font-mono text-[11px]">signals-scout-*</span>{' '}
                    skills in your PostHog project.
                </span>
                <ScoutHelperSkillLinks />
            </div>
        </div>
    )
}

/** Actions for the roster, lifted into the scene header so they sit in one predictable place. */
export function ScoutsRosterActions(): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)
    return (
        <>
            <AskAboutScoutsMenu />
            <ScoutSuggestButton type="secondary" size="small" />
            <ScoutCreateButton size="small" onCreated={() => loadScoutConfigs()} />
        </>
    )
}

/**
 * The templated chat kickoffs, behind one button. As peers of "Create scout" they read as primary
 * actions, which they aren't — each one navigates away to a task rather than changing anything here.
 */
function AskAboutScoutsMenu(): JSX.Element {
    const { startScoutChatTask } = useActions(scoutFleetLogic)
    const { runningChatType, aiConsentDisabledReason } = useValues(scoutFleetLogic)
    const prompts: { label: string; chatType: ScoutChatType }[] = [
        { label: 'How is my scout troop performing?', chatType: 'fleet_overview' },
        { label: 'What signals were emitted recently?', chatType: 'recent_signals' },
    ]

    return (
        <LemonMenu
            items={prompts.map(({ label, chatType }) => ({
                label,
                onClick: () => startScoutChatTask(chatType, label),
                disabledReason: runningChatType !== null ? 'Starting a task…' : (aiConsentDisabledReason ?? undefined),
            }))}
        >
            <LemonButton type="secondary" size="small" icon={<IconSparkles />} loading={runningChatType !== null}>
                Ask
            </LemonButton>
        </LemonMenu>
    )
}

function Stat({ value, label, alert = false }: { value: string; label: string; alert?: boolean }): JSX.Element {
    return (
        <div className="flex flex-col border-r border-primary pr-4 last:border-r-0">
            <span className={cn('text-lg font-semibold tabular-nums leading-tight', alert && 'text-danger')}>
                {value}
            </span>
            <span className="text-[11px] text-muted">{label}</span>
        </div>
    )
}

/**
 * Headline numbers on the left, search and the tag filter pushed right on the same line. They were
 * two stacked rows before, which burned a whole row of height at every width — `ml-auto` keeps the
 * search right-aligned, and the row only wraps once the two halves genuinely can't share a line.
 */
function RosterHeader(): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-6 pt-4 pb-3">
            <RosterStats />
            <RosterFilters />
        </div>
    )
}

/**
 * The troop's headline numbers. Output is stated as reports filed rather than as a run success
 * rate: every run completing tells you nothing crashed, not that the troop is earning its keep.
 */
function RosterStats(): JSX.Element {
    const { rosterGroupCounts, enabledCount, emittedFindingsSummary } = useValues(scoutFleetLogic)

    return (
        <div className="flex flex-wrap items-center gap-4">
            {rosterGroupCounts.needs_you > 0 && (
                <Stat value={String(rosterGroupCounts.needs_you)} label="need you" alert />
            )}
            <Stat value={String(enabledCount)} label="on patrol" />
            <Tooltip title="New reports your scouts filed across their recent runs. Reports they only added to aren't counted here.">
                <span>
                    <Stat value={String(emittedFindingsSummary.authoredReportCount)} label="reports filed" />
                </span>
            </Tooltip>
        </div>
    )
}

function RosterFilters(): JSX.Element {
    const { scoutSearch, scoutEnabledFilter, scoutTagOptions, activeScoutTags } = useValues(scoutFleetLogic)
    const { setScoutSearch, setScoutEnabledFilter, setScoutTagFilter } = useActions(scoutFleetLogic)

    return (
        <div className="ml-auto flex flex-wrap items-center gap-2">
            <LemonSegmentedButton
                size="small"
                value={scoutEnabledFilter}
                onChange={setScoutEnabledFilter}
                options={[
                    { value: 'all', label: 'All' },
                    { value: 'enabled', label: 'On' },
                    { value: 'disabled', label: 'Off' },
                ]}
            />
            <LemonInput
                type="search"
                size="small"
                placeholder="Search scouts…"
                value={scoutSearch}
                onChange={setScoutSearch}
                className="w-56"
                allowClear
            />
            {scoutTagOptions.length > 0 && (
                <>
                    <ScoutTagsFilter
                        options={scoutTagOptions}
                        selected={activeScoutTags}
                        onToggle={(tag) =>
                            setScoutTagFilter(
                                activeScoutTags.includes(tag)
                                    ? activeScoutTags.filter((candidate) => candidate !== tag)
                                    : [...activeScoutTags, tag]
                            )
                        }
                        onClear={() => setScoutTagFilter([])}
                    />
                </>
            )}
        </div>
    )
}

function RosterGroups(): JSX.Element {
    const { rosterBuckets } = useValues(scoutFleetLogic)

    if (rosterBuckets.length === 0) {
        return <span className="px-6 py-6 text-sm text-muted">No scouts match the current filters.</span>
    }

    return (
        <div className="flex flex-col">
            {rosterBuckets.map((bucket, index) => (
                <RosterGroup key={bucket.key} bucket={bucket} showHeader={index === 0} />
            ))}
        </div>
    )
}

const GROUP_HEADING_CLASS: Record<ScoutGroupKey, string> = {
    needs_you: 'bg-danger-highlight text-danger',
    working: 'bg-surface-secondary text-secondary',
    watching: 'bg-surface-secondary text-secondary',
    dry_run: 'bg-surface-secondary text-secondary',
    settling_in: 'bg-surface-secondary text-secondary',
    off: 'bg-surface-secondary text-secondary',
}

function RosterGroup({ bucket, showHeader }: { bucket: ScoutGroupBucket; showHeader: boolean }): JSX.Element {
    const { rollups, updatingScoutIds } = useValues(scoutFleetLogic)
    const { updateScoutConfig } = useActions(scoutFleetLogic)
    const { currentTeam } = useValues(teamLogic)
    const timezone = currentTeam?.timezone ?? 'UTC'
    const now = new Date()
    const hint = SCOUT_GROUP_HINT[bucket.key]
    // Watching holds the watchdogs whose silence is the job, so say so on the group rather than
    // leaving a reader to wonder why a scout with no output is fine.
    const exemptCount =
        bucket.key === 'watching' ? bucket.configs.filter((config) => config.auto_pause_exempt).length : 0

    return (
        <div className="flex flex-col">
            <div
                className={cn(
                    'flex items-center gap-2 border-y border-primary px-6 py-1 text-[11px] font-semibold uppercase tracking-wide',
                    GROUP_HEADING_CLASS[bucket.key]
                )}
            >
                <span>{SCOUT_GROUP_LABEL[bucket.key]}</span>
                <span className="font-medium opacity-60">{bucket.configs.length}</span>
                {hint && (
                    <span className="font-normal normal-case tracking-normal opacity-70">
                        {hint}
                        {exemptCount > 0 && ` — ${exemptCount} quiet by design`}
                    </span>
                )}
            </div>
            <LemonTable
                embedded
                size="small"
                showHeader={showHeader}
                rowKey={(config: SignalScoutConfig) => config.id}
                dataSource={bucket.configs}
                rowClassName={(config: SignalScoutConfig) => cn('cursor-pointer', !config.enabled && 'opacity-65')}
                onRow={(config: SignalScoutConfig) => ({
                    onClick: () => router.actions.push(urls.inboxScout(config.skill_name)),
                })}
                columns={[
                    {
                        title: 'Scout',
                        key: 'scout',
                        width: '34%',
                        render: (_, config: SignalScoutConfig) => (
                            <ScoutNameCell config={config} group={bucket.key} rollup={rollups.get(config.skill_name)} />
                        ),
                    },
                    {
                        title: 'Cadence',
                        key: 'cadence',
                        width: '12%',
                        render: (_, config: SignalScoutConfig) => (
                            <span className="text-xs text-secondary">{scoutCadenceLabel(config)}</span>
                        ),
                    },
                    {
                        title: 'Next run',
                        key: 'nextRun',
                        width: '12%',
                        render: (_, config: SignalScoutConfig) => {
                            const next = nextRunAt(config, timezone, now)
                            return next ? (
                                <span className="text-xs text-secondary tabular-nums">
                                    <TZLabel time={next.toISOString()} />
                                </span>
                            ) : (
                                <span className="text-xs text-muted">—</span>
                            )
                        },
                    },
                    {
                        title: 'Recent runs',
                        key: 'runs',
                        width: '30%',
                        // The strip is a timeline ending at "now", anchored right so every row's
                        // newest run shares one vertical line; the header follows its content.
                        align: 'right',
                        render: (_, config: SignalScoutConfig) => {
                            const runs = rollups.get(config.skill_name)?.runs ?? []
                            return runs.length ? (
                                <ScoutRunBoxes runs={runs} />
                            ) : (
                                <span className="text-xs text-muted">No runs yet</span>
                            )
                        },
                    },
                    {
                        title: '',
                        key: 'enabled',
                        width: '8%',
                        render: (_, config: SignalScoutConfig) => (
                            // Stop the row's navigation: flipping a scout off is not a request to
                            // open it, and landing on its page afterwards hides the row you just changed.
                            <div
                                className="flex justify-end"
                                onClick={(event) => event.stopPropagation()}
                                onKeyDown={(event) => event.stopPropagation()}
                                role="presentation"
                            >
                                <ScoutEnabledSwitch
                                    config={config}
                                    onUpdate={updateScoutConfig}
                                    updating={updatingScoutIds.includes(config.id)}
                                />
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}

const SUBTITLE_TONE_CLASS = {
    danger: 'text-danger',
    warning: 'text-warning',
    muted: 'text-muted',
} as const

function ScoutNameCell({
    config,
    group,
    rollup,
}: {
    config: SignalScoutConfig
    group: ScoutGroupKey
    rollup: ScoutRollup | undefined
}): JSX.Element {
    const subtitle = scoutSubtitle(config, rollup, new Date())
    return (
        <div className="flex flex-col gap-0.5 py-0.5">
            <div className="flex items-center gap-2">
                <ScoutStatusDot group={group} />
                <Link to={urls.inboxScout(config.skill_name)} subtle className="truncate text-sm font-medium">
                    {prettifyScoutSkillName(config.skill_name)}
                </Link>
                {config.auto_pause_exempt && group === 'watching' && (
                    <Tooltip title="Exempt from auto-pause — this scout is supposed to stay quiet">
                        <LemonTag size="small">Quiet by design</LemonTag>
                    </Tooltip>
                )}
                {!config.emit && (
                    <Tooltip title="This scout runs and investigates, but nothing it finds reaches your inbox">
                        <LemonTag size="small" type="option">
                            Dry run
                        </LemonTag>
                    </Tooltip>
                )}
            </div>
            {subtitle && (
                <span className={cn('ml-4 line-clamp-1 text-[11.5px]', SUBTITLE_TONE_CLASS[subtitle.tone])}>
                    {subtitle.text}
                </span>
            )}
        </div>
    )
}

function ScoutsEmptyState(): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)

    return (
        <div className="m-6 flex flex-col items-start gap-2 rounded border border-primary bg-surface-primary px-5 py-5">
            <div className="flex items-center gap-2">
                <IconCompass className="size-[18px] text-accent" />
                <span className="text-sm font-medium text-default">No scouts on this project yet</span>
            </div>
            <p className="mb-0 max-w-2xl text-xs leading-snug text-secondary">
                Create a scout to investigate a recurring signal or behavior on a schedule.
            </p>
            <div className="flex flex-wrap items-center gap-2">
                <ScoutCreateButton onCreated={() => loadScoutConfigs()} />
                <ScoutSuggestButton />
            </div>
            <ScoutHelperSkillLinks />
        </div>
    )
}
