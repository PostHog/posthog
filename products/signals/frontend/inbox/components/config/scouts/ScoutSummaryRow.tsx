import { useValues } from 'kea'

import { IconArrowUpRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'

import { nextRunAt } from '../../../utils/scoutGroups'
import { scoutDisplayName } from '../../../utils/scoutRunsWindow'
import { ScoutLifecycleBadge } from './ScoutBadges'
import { ScoutCadenceLabel } from './ScoutCadenceLabel'
import { ScoutEnabledSwitch } from './ScoutConfigControls'
import { ScoutNextRunLabel } from './ScoutNextRunLabel'

/**
 * A compact scout row for surfaces outside the roster — product pages that show the handful of
 * scouts they own (e.g. AI observability). Deliberately read-mostly: name, cadence, the enable
 * switch, and a link into the scout's own page, which is where the rest of it lives.
 */
export function ScoutSummaryRow({
    config,
    onUpdate,
    updating = false,
}: {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const timezone = currentTeam?.timezone ?? 'UTC'
    const hasNextRun = nextRunAt(config, timezone, new Date()) !== null

    return (
        <div
            className={cn(
                'flex flex-wrap items-center gap-x-4 gap-y-2 rounded border border-primary bg-surface-primary px-4 py-2.5',
                !config.enabled && 'opacity-65'
            )}
        >
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex items-center gap-2">
                    <Tooltip title={config.description || undefined}>
                        <Link
                            to={urls.inboxScout(config.skill_name)}
                            subtle
                            className="truncate text-sm font-medium min-w-[6rem]"
                        >
                            {scoutDisplayName(config)}
                        </Link>
                    </Tooltip>
                    {!config.emit && (
                        <LemonTag size="small" type="option">
                            Dry run
                        </LemonTag>
                    )}
                    <ScoutLifecycleBadge config={config} />
                </div>
                <span className="text-[11px] text-muted">
                    <ScoutCadenceLabel config={config} />
                    {hasNextRun && (
                        <>
                            {' · next run '}
                            <ScoutNextRunLabel config={config} />
                        </>
                    )}
                </span>
            </div>
            <div className="flex shrink-0 items-center gap-2">
                <ScoutEnabledSwitch config={config} onUpdate={onUpdate} updating={updating} />
                <Tooltip title="Open this scout">
                    <LemonButton
                        size="small"
                        icon={<IconArrowUpRight />}
                        to={urls.inboxScout(config.skill_name)}
                        aria-label={`Open the ${config.skill_name} scout`}
                    />
                </Tooltip>
            </div>
        </div>
    )
}
