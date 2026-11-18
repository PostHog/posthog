import { useActions, useValues } from 'kea'

import {
    IconArrowRight,
    IconCalendar,
    IconCheck,
    IconCopy,
    IconFlag,
    IconGear,
    IconHourglass,
    IconPencil,
    IconRefresh,
    IconWarning,
} from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    DatePicker,
    Dot,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Progress,
    Separator,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { pluralize } from 'lib/utils/strings'
import { AnalyticsOwnerAvatar } from 'scenes/analytics/AnalyticsOwner'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { modalsLogic } from 'scenes/experiments/modalsLogic'
import { isLegacyExperiment } from 'scenes/experiments/utils'
import { urls } from 'scenes/urls'

import { Experiment } from '~/types'

import { QuillStatusBadge, EXPERIMENT_CONCLUSION_DOT } from 'products/experiments/frontend/components/QuillStatusBadge'
import { useTruncatedText } from 'products/experiments/frontend/components/TruncatedText'
import { CONCLUSION_DISPLAY_CONFIG } from 'products/experiments/frontend/constants'
import { getExperimentStatus, isExperimentPaused } from 'products/experiments/frontend/experimentStatus'
import { useHealthChip } from 'products/experiments/frontend/health/ExperimentHealthChip'
import { RunningTimeConfigModal } from 'products/experiments/frontend/modals/RunningTimeConfigModal/RunningTimeConfigModal'

import { useClampedComment } from './ExperimentConclusionComment'
import { useDateTrigger } from './ExperimentDateRange'
import { useFlagCleanupStatus } from './ExperimentFlagCleanupStatus'
import { refreshStaleness } from './ExperimentLastRefreshText'
import { PAUSED_TOOLTIP, getExperimentMetaBarVisibility, getExperimentStatsSummary } from './experimentMetaBarUtils'
import { refreshLoadingText, useExperimentRefresh } from './ExperimentRefreshButton'
import { useRemainingTime } from './ExperimentRemainingTime'

function WithTooltip({ tooltip, children }: { tooltip: React.ReactNode; children: React.ReactElement }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={children} />
            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
        </Tooltip>
    )
}

function MetaIcon({ tooltip, children }: { tooltip: string; children: React.ReactNode }): JSX.Element {
    return (
        <WithTooltip tooltip={tooltip}>
            <span className="flex shrink-0 text-base text-muted-foreground">{children}</span>
        </WithTooltip>
    )
}

function HealthChip(): JSX.Element | null {
    const chip = useHealthChip()
    if (!chip) {
        return null
    }
    return (
        <Button
            variant="outline"
            size="sm"
            tooltip="Show the health checks"
            onClick={chip.openHealthTab}
            data-attr="experiment-health-chip"
        >
            <IconWarning className={chip.hasCritical ? 'text-destructive-foreground' : 'text-warning-foreground'} />
            {pluralize(chip.count, 'issue')}
        </Button>
    )
}

function ConclusionItem({ experiment }: { experiment: Experiment }): JSX.Element | null {
    if (!experiment.conclusion) {
        return null
    }
    const config = CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]
    return (
        <WithTooltip tooltip={config.description}>
            <span className="flex items-center gap-1.5" tabIndex={0} data-attr="experiment-conclusion">
                <Dot variant={EXPERIMENT_CONCLUSION_DOT[experiment.conclusion] ?? 'default'} />
                <Text size="xs" weight="semibold" render={<span />}>
                    {config.title}
                </Text>
            </span>
        </WithTooltip>
    )
}

function FlagKey({ flagKey }: { flagKey: string }): JSX.Element {
    const { display, fullText, setElement } = useTruncatedText(flagKey, 32)
    const text = (
        <span ref={setElement} className="truncate">
            {display}
        </span>
    )
    return fullText ? <WithTooltip tooltip={fullText}>{text}</WithTooltip> : text
}

function DateTrigger({
    date,
    boundary,
    onApply,
}: {
    date: string | null | undefined
    boundary: 'start' | 'end'
    onApply: (date: string) => void
}): JSX.Element {
    const { isOpen, open, close, label, disabledReason } = useDateTrigger(date, boundary)

    return (
        <Popover open={isOpen} onOpenChange={(next: boolean) => (next ? open() : close())}>
            <PopoverTrigger
                render={
                    <Button
                        size="sm"
                        disabledReason={disabledReason}
                        tooltip={date ? `${boundary === 'start' ? 'Start date' : 'End date'}` : undefined}
                        data-attr={`experiment-${boundary}-date`}
                    />
                }
            >
                {label}
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-0">
                <DatePicker
                    value={date ? dayjs(date).toDate() : new Date()}
                    maxDate={boundary === 'start' ? new Date() : dayjs().add(5, 'year').toDate()}
                    showTime
                    onApply={(value: Date) => onApply(value.toISOString())}
                    onCancel={close}
                />
            </PopoverContent>
        </Popover>
    )
}

function DateRange({ experiment }: { experiment: Experiment }): JSX.Element {
    const { changeExperimentStartDate, changeExperimentEndDate } = useActions(experimentLogic)
    return (
        <span className="flex items-center gap-0.5" data-attr="experiment-date-range">
            <MetaIcon tooltip="Duration">
                <IconCalendar />
            </MetaIcon>
            <DateTrigger date={experiment.start_date} boundary="start" onApply={changeExperimentStartDate} />
            <IconArrowRight className="shrink-0 text-muted-foreground" />
            <DateTrigger date={experiment.end_date} boundary="end" onApply={changeExperimentEndDate} />
        </span>
    )
}

function RemainingTime({ experiment, onConfigure }: { experiment: Experiment; onConfigure: () => void }): JSX.Element {
    const { state, showProgress, iconTooltip, configureTooltip } = useRemainingTime(experiment)

    let content: JSX.Element
    if (state.kind === 'calculating') {
        content = (
            <Text size="xs" variant="muted" render={<span />}>
                Calculating…
            </Text>
        )
    } else if (state.kind === 'pending') {
        content = (
            <Text size="xs" variant="muted" render={<span />}>
                {state.label}
            </Text>
        )
    } else if (state.kind === 'complete') {
        content = (
            <span className="flex items-center gap-1">
                <IconCheck className="text-success-foreground" />
                Target reached
            </span>
        )
    } else if (state.kind === 'out-of-reach') {
        content = (
            <WithTooltip tooltip={state.tooltip}>
                <span className="flex items-center gap-1.5" tabIndex={0}>
                    <IconWarning className="shrink-0 text-base text-warning-foreground" />
                    {state.label}
                </span>
            </WithTooltip>
        )
    } else {
        content = (
            <span className="flex items-center gap-1.5">
                {state.progress !== null && (
                    <Progress value={state.progress * 100} className="w-10" aria-label="Progress to target" />
                )}
                {state.label}
            </span>
        )
    }

    return (
        <span className="flex items-center gap-1.5" data-attr="experiment-remaining-time">
            {!showProgress && (
                <MetaIcon tooltip={iconTooltip}>
                    <IconHourglass />
                </MetaIcon>
            )}
            {content}
            <Button
                size="icon-xs"
                aria-label={configureTooltip}
                tooltip={configureTooltip}
                onClick={onConfigure}
                data-attr="experiment-running-time-config"
            >
                <IconGear />
            </Button>
        </span>
    )
}

function RefreshButton({ experiment }: { experiment: Experiment }): JSX.Element {
    const { isRefreshing, lastRefresh, progress, queuedHint, blockedReason, onRefresh } =
        useExperimentRefresh(experiment)
    const staleness = refreshStaleness(lastRefresh)

    return (
        <Button
            variant="outline"
            size="sm"
            loading={isRefreshing}
            onClick={onRefresh}
            disabledReason={isRefreshing ? queuedHint : blockedReason}
            aria-label={isRefreshing ? undefined : 'Refresh results'}
            data-attr="refresh-experiment"
        >
            {!isRefreshing && <IconRefresh />}
            {isRefreshing ? (
                refreshLoadingText(progress)
            ) : (
                <span className="flex items-center gap-1">
                    <span className="text-muted-foreground">Refreshed</span>
                    <span
                        className={cn(
                            staleness === 'stale' && 'text-destructive-foreground',
                            staleness === 'ageing' && 'text-warning-foreground'
                        )}
                    >
                        {lastRefresh ? <TZLabel time={lastRefresh} className="align-baseline" /> : 'a while ago'}
                    </span>
                </span>
            )}
        </Button>
    )
}

function ConclusionCard({ experiment }: { experiment: Experiment }): JSX.Element | null {
    const { openEditConclusionModal } = useActions(modalsLogic)
    const comment = useClampedComment(experiment.conclusion_comment ?? '')

    if (!experiment.conclusion) {
        return null
    }

    return (
        <Card size="sm" data-attr="experiment-conclusion-card">
            <CardContent className="flex flex-col gap-1">
                <span className="flex items-center gap-1">
                    <Text size="sm" weight="semibold" render={<span />}>
                        Conclusion
                    </Text>
                    <Button
                        size="icon-xs"
                        aria-label="Edit conclusion"
                        tooltip="Edit conclusion"
                        onClick={openEditConclusionModal}
                        data-attr="experiment-edit-conclusion"
                    >
                        <IconPencil />
                    </Button>
                </span>
                {experiment.conclusion_comment ? (
                    <>
                        <Text
                            size="xs"
                            render={
                                <p
                                    ref={comment.textRef}
                                    id="experiment-conclusion-comment-text"
                                    className={cn(
                                        'm-0 whitespace-pre-wrap break-words leading-relaxed',
                                        !comment.isExpanded && 'max-h-36 overflow-hidden'
                                    )}
                                />
                            }
                        >
                            {experiment.conclusion_comment}
                        </Text>
                        {comment.showToggle && (
                            <Button
                                size="sm"
                                className="self-start"
                                aria-expanded={comment.isExpanded}
                                aria-controls="experiment-conclusion-comment-text"
                                onClick={comment.toggle}
                                data-attr="experiment-conclusion-toggle"
                            >
                                {comment.isExpanded ? 'Show less' : 'Show more'}
                            </Button>
                        )}
                    </>
                ) : (
                    <Text size="xs" variant="muted" render={<p className="m-0 italic" />}>
                        Add a note about why this experiment ended
                    </Text>
                )}
            </CardContent>
        </Card>
    )
}

function FlagCleanupStatus({ experimentId, taskId }: { experimentId: number; taskId: string }): JSX.Element | null {
    const status = useFlagCleanupStatus(experimentId, taskId)
    if (!status) {
        return null
    }
    return (
        <span className="flex flex-wrap items-center gap-x-1.5 text-xs" data-attr="experiment-flag-cleanup">
            <span className="text-muted-foreground">Flag cleanup</span>
            <span className="text-muted-foreground">·</span>
            <span>{status.text}</span>
            {status.showLink && (
                <Button
                    variant="link"
                    size="inline"
                    nativeButton={false}
                    render={<LinkPrimitive to={status.linkUrl} target={status.isExternalLink ? '_blank' : undefined} />}
                >
                    {status.isExternalLink ? 'View on GitHub' : 'View task'}
                </Button>
            )}
        </span>
    )
}

export function QuillExperimentMetaBar(): JSX.Element | null {
    const { experiment, statsMethod, isSingleVariantShipped, shippedVariantKey } = useValues(experimentLogic)
    const { openRunningTimeConfigModal } = useActions(modalsLogic)

    if (!experiment.feature_flag) {
        return null
    }

    const status = getExperimentStatus(experiment)
    const isPaused = isExperimentPaused(experiment)
    const visibility = getExperimentMetaBarVisibility(experiment, isLegacyExperiment(experiment))
    const stats = getExperimentStatsSummary(experiment, statsMethod)
    const { created_by } = experiment
    const flagKey = experiment.feature_flag.key

    const items: { key: string; node: React.ReactNode; className?: string; dataAttr?: string }[] = [
        {
            key: 'status',
            dataAttr: 'experiment-status',
            node: (
                <>
                    {isPaused ? (
                        <WithTooltip tooltip={PAUSED_TOOLTIP}>
                            <span tabIndex={0}>
                                <QuillStatusBadge status={status} />
                            </span>
                        </WithTooltip>
                    ) : (
                        <QuillStatusBadge status={status} />
                    )}
                    {isSingleVariantShipped && (
                        <WithTooltip tooltip={`Variant "${shippedVariantKey}" is rolled out to 100% of users`}>
                            <Badge variant="completed" tabIndex={0}>
                                100% rollout
                            </Badge>
                        </WithTooltip>
                    )}
                    <HealthChip />
                </>
            ),
        },
        ...(visibility.showConclusion ? [{ key: 'conclusion', node: <ConclusionItem experiment={experiment} /> }] : []),
        {
            key: 'flag',
            dataAttr: 'experiment-feature-flag',
            className: 'min-w-0',
            node: (
                <>
                    {isPaused && (
                        <WithTooltip tooltip={PAUSED_TOOLTIP}>
                            <span className="flex shrink-0 text-base text-destructive-foreground">
                                <IconWarning />
                            </span>
                        </WithTooltip>
                    )}
                    <MetaIcon tooltip="Feature flag">
                        <IconFlag />
                    </MetaIcon>
                    <FlagKey flagKey={flagKey} />
                    <Button
                        size="icon-xs"
                        aria-label="Copy feature flag key"
                        tooltip="Copy feature flag key"
                        onClick={() => void copyToClipboard(flagKey, 'feature flag key')}
                    >
                        <IconCopy />
                    </Button>
                    <Button
                        size="icon-xs"
                        aria-label="Open feature flag"
                        tooltip="Open feature flag"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.featureFlag(experiment.feature_flag.id)} target="_blank" />}
                        data-attr="experiment-open-feature-flag"
                    >
                        <IconOpenInNew />
                    </Button>
                </>
            ),
        },
        {
            key: 'stats',
            node: (
                <WithTooltip tooltip={stats.description}>
                    <span className="flex items-center gap-1.5" tabIndex={0} data-attr="experiment-stats-method">
                        <span>{stats.method}</span>
                        <span className="text-muted-foreground">·</span>
                        <span>{stats.level}</span>
                    </span>
                </WithTooltip>
            ),
        },
        ...(visibility.showDateRange ? [{ key: 'dates', node: <DateRange experiment={experiment} /> }] : []),
        ...(visibility.showRemainingTime
            ? [
                  {
                      key: 'remaining',
                      node: <RemainingTime experiment={experiment} onConfigure={openRunningTimeConfigModal} />,
                  },
              ]
            : []),
    ]

    return (
        <div className="-mt-2 flex flex-col gap-2" data-attr="experiment-meta-bar">
            <div className="flex items-start justify-between gap-x-3 text-xs">
                <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
                    {items.map((item, index) => (
                        <div
                            key={item.key}
                            className={cn('flex items-center gap-1.5', item.className)}
                            data-attr={item.dataAttr}
                        >
                            {index > 0 && <Separator orientation="vertical" className="mr-1.5 h-4" />}
                            {item.node}
                        </div>
                    ))}
                </div>
                {(visibility.showRefresh || created_by) && (
                    <div className="flex shrink-0 items-center gap-2" data-attr="experiment-meta-bar-actions">
                        {visibility.showRefresh && <RefreshButton experiment={experiment} />}
                        {created_by && (
                            <WithTooltip tooltip={`Created by ${created_by.first_name || created_by.email}`}>
                                <span className="flex items-center" tabIndex={0}>
                                    <AnalyticsOwnerAvatar owner={created_by} />
                                </span>
                            </WithTooltip>
                        )}
                    </div>
                )}
            </div>

            {visibility.showConclusion && <ConclusionCard experiment={experiment} />}

            {experiment.flag_cleanup_task_id && typeof experiment.id === 'number' && (
                <FlagCleanupStatus experimentId={experiment.id} taskId={experiment.flag_cleanup_task_id} />
            )}

            {visibility.showRemainingTime && <RunningTimeConfigModal experiment={experiment} />}
        </div>
    )
}
