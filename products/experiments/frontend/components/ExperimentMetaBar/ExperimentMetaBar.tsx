import { useActions, useValues } from 'kea'

import { IconFlag, IconWarning } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTag, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { modalsLogic } from 'scenes/experiments/modalsLogic'
import { urls } from 'scenes/urls'

import { StatusTag } from 'products/experiments/frontend/components/StatusTag'
import { TruncatedText } from 'products/experiments/frontend/components/TruncatedText'
import { getExperimentStatus, isExperimentPaused } from 'products/experiments/frontend/experimentStatus'
import { RunningTimeConfigModal } from 'products/experiments/frontend/modals/RunningTimeConfigModal/RunningTimeConfigModal'

import { ExperimentConclusionCard } from './ExperimentConclusionCard'
import { ExperimentConclusionItem } from './ExperimentConclusionItem'
import { ExperimentDateRange } from './ExperimentDateRange'
import { ExperimentFlagCleanupStatus } from './ExperimentFlagCleanupStatus'
import { getExperimentMetaBarVisibility, getExperimentStatsSummary } from './experimentMetaBarUtils'
import { ExperimentRefreshButton } from './ExperimentRefreshButton'
import { ExperimentRemainingTime } from './ExperimentRemainingTime'

const PAUSED_TOOLTIP = 'This experiment is paused. The linked flag is disabled and no data is collected.'

// Every item carries its own leading divider and the row starts inside a clipped gutter, so the
// first item on each wrapped line hides its divider there instead of leaving one dangling.
function MetaItem({ children, className, ...rest }: React.HTMLAttributes<HTMLDivElement>): JSX.Element {
    return (
        <div className={cn('flex items-center gap-1.5 ml-3', className)} {...rest}>
            <LemonDivider vertical className="h-4 self-center mr-3 shrink-0" />
            {children}
        </div>
    )
}

export function ExperimentMetaBar(): JSX.Element | null {
    const { experiment, statsMethod, isSingleVariantShipped, shippedVariantKey } = useValues(experimentLogic)
    const { openRunningTimeConfigModal } = useActions(modalsLogic)

    if (!experiment.feature_flag) {
        return null
    }

    const status = getExperimentStatus(experiment)
    const isPaused = isExperimentPaused(experiment)
    const visibility = getExperimentMetaBarVisibility(experiment)
    const stats = getExperimentStatsSummary(experiment, statsMethod)
    const { created_by } = experiment

    // The title keeps 8px of inner padding and the tabs pull up 16px, so the band sits midway only when pulled up 8px.
    return (
        <div className="flex flex-col gap-2 -mt-2" data-attr="experiment-meta-bar">
            {/* The gutter is 12px gap + 1px divider + 12px gap; the 4px clip margin keeps focus rings visible. */}
            <div className="overflow-x-clip [overflow-clip-margin:4px]">
                <div className="flex flex-wrap items-center gap-y-2 -ml-[25px] text-sm">
                    <MetaItem className="gap-1" data-attr="experiment-status">
                        {isPaused ? (
                            <Tooltip title={PAUSED_TOOLTIP}>
                                <StatusTag status={status} />
                            </Tooltip>
                        ) : (
                            <StatusTag status={status} />
                        )}
                        {isSingleVariantShipped && (
                            <Tooltip title={`Variant "${shippedVariantKey}" is rolled out to 100% of users`}>
                                <LemonTag type="completion" className="cursor-default">
                                    <b className="uppercase">100% rollout</b>
                                </LemonTag>
                            </Tooltip>
                        )}
                    </MetaItem>

                    {visibility.showConclusion && (
                        <MetaItem>
                            <ExperimentConclusionItem />
                        </MetaItem>
                    )}

                    <MetaItem className="min-w-0" data-attr="experiment-feature-flag">
                        {isPaused && (
                            <Tooltip title={PAUSED_TOOLTIP}>
                                <IconWarning className="text-danger text-base shrink-0" />
                            </Tooltip>
                        )}
                        <Tooltip title="Feature flag">
                            <IconFlag className="text-secondary text-base shrink-0" />
                        </Tooltip>
                        <TruncatedText text={experiment.feature_flag.key} maxLength={32} />
                        <CopyToClipboardInline
                            explicitValue={experiment.feature_flag.key}
                            description="feature flag key"
                        />
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            to={urls.featureFlag(experiment.feature_flag.id)}
                            targetBlank
                            hideExternalLinkIcon
                            icon={<IconOpenInNew />}
                            tooltip="Open feature flag"
                            aria-label="Open feature flag"
                            data-attr="experiment-open-feature-flag"
                        />
                    </MetaItem>

                    <MetaItem>
                        <Tooltip title={stats.description}>
                            <span
                                className="flex items-center gap-1.5 cursor-default"
                                data-attr="experiment-stats-method"
                            >
                                <span>{stats.method}</span>
                                <span className="text-secondary">·</span>
                                <span>{stats.level}</span>
                            </span>
                        </Tooltip>
                    </MetaItem>

                    {visibility.showDateRange && (
                        <MetaItem>
                            <ExperimentDateRange />
                        </MetaItem>
                    )}

                    {visibility.showRemainingTime && (
                        <MetaItem>
                            <ExperimentRemainingTime experiment={experiment} onConfigure={openRunningTimeConfigModal} />
                        </MetaItem>
                    )}

                    {/* Right-aligned only when the scene column is wide enough for one line; below that it flows with the facts. */}
                    {(visibility.showRefresh || created_by) && (
                        <MetaItem className="gap-2 @min-[72rem]/main-content:ml-auto @min-[72rem]/main-content:[&>[role=separator]]:hidden">
                            {visibility.showRefresh && <ExperimentRefreshButton experiment={experiment} />}
                            {created_by && (
                                <Tooltip title={`Created by ${created_by.first_name || created_by.email}`}>
                                    <span className="flex items-center">
                                        <ProfilePicture user={created_by} size="md" />
                                    </span>
                                </Tooltip>
                            )}
                        </MetaItem>
                    )}
                </div>
            </div>

            {visibility.showConclusion && <ExperimentConclusionCard />}

            {experiment.flag_cleanup_task_id && typeof experiment.id === 'number' && (
                <ExperimentFlagCleanupStatus experimentId={experiment.id} taskId={experiment.flag_cleanup_task_id} />
            )}

            {visibility.showRemainingTime && <RunningTimeConfigModal experiment={experiment} />}
        </div>
    )
}
