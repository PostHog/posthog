import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTable } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import {
    SCOUT_GROUP_HINT,
    SCOUT_GROUP_LABEL,
    ScoutGroupBucket,
    ScoutGroupKey,
    scoutCadenceLabel,
} from '../../../utils/scoutGroups'
import { ScoutEnabledSwitch } from './ScoutConfigControls'
import { ScoutNameCell } from './ScoutNameCell'
import { ScoutNextRunLabel } from './ScoutNextRunLabel'
import { ScoutRunBoxes } from './ScoutRunBoxes'

const GROUP_HEADING_CLASS: Record<ScoutGroupKey, string> = {
    needs_you: 'bg-danger-highlight text-danger',
    working: 'bg-surface-secondary text-secondary',
    watching: 'bg-surface-secondary text-secondary',
    dry_run: 'bg-surface-secondary text-secondary',
    settling_in: 'bg-surface-secondary text-secondary',
    off: 'bg-surface-secondary text-secondary',
}

export function ScoutsRosterGroup({
    bucket,
    showHeader,
}: {
    bucket: ScoutGroupBucket
    showHeader: boolean
}): JSX.Element {
    const { rollups, updatingScoutIds, scoutRunsLoadedOnce } = useValues(scoutFleetLogic)
    const { updateScoutConfig } = useActions(scoutFleetLogic)
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
                    // The row is one big target for the scout page, but a link or button inside it
                    // (a run box, the name) already navigates itself: a second push here would
                    // override the run box's task URL.
                    onClick: (event) => {
                        if ((event.target as HTMLElement).closest('a, button')) {
                            return
                        }
                        router.actions.push(urls.inboxScout(config.skill_name))
                    },
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
                        render: (_, config: SignalScoutConfig) => (
                            <span className="text-xs text-secondary tabular-nums">
                                <ScoutNextRunLabel config={config} />
                            </span>
                        ),
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
                            if (runs.length) {
                                return <ScoutRunBoxes runs={runs} />
                            }
                            // Until the runs request has landed once, an empty rollup means "not
                            // loaded", not "never ran"; the poll retries a failed load on its own.
                            return scoutRunsLoadedOnce ? (
                                <span className="text-xs text-muted">No runs yet</span>
                            ) : (
                                <span className="text-xs text-muted">…</span>
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
