import { useActions, useValues } from 'kea'

import {
    IconBrackets,
    IconChevronLeft,
    IconChevronRight,
    IconExpand45,
    IconGraph,
    IconListTree,
    IconPin,
    IconPinFilled,
} from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconLink } from 'lib/lemon-ui/icons'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { logsMetricRuleQuickCreateLogic } from 'products/logs/frontend/components/LogsMetricRules/logsMetricRuleQuickCreateLogic'
import { buildMetricRuleSeedFromLog } from 'products/logs/frontend/components/LogsMetricRules/metricRuleSeed'
import { CopyLogButton } from 'products/logs/frontend/components/LogsViewer/CopyLogButton'
import { LogContextSelector } from 'products/logs/frontend/components/LogsViewer/LogContextSelector/LogContextSelector'
import { logDetailsModalLogic } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { useCellScrollControls } from 'products/logs/frontend/components/VirtualizedLogsList/useCellScroll'
import { logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'
import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'
import { ParsedLogMessage } from 'products/logs/frontend/types'
import { getSessionIdFromLogAttributes } from 'products/logs/frontend/utils'
import { traceUrl } from 'products/tracing/frontend/traceLinks'

import { FABGroup } from './FABGroup'

export interface LogRowFABProps {
    log: ParsedLogMessage
    pinned: boolean
    isPrettified: boolean
    onTogglePin: (log: ParsedLogMessage) => void
    onTogglePrettify?: (log: ParsedLogMessage) => void
    showScrollButtons?: boolean
}

export function LogRowFAB({
    log,
    pinned,
    isPrettified,
    onTogglePin,
    onTogglePrettify,
    showScrollButtons = false,
}: LogRowFABProps): JSX.Element {
    const { id } = useValues(logsViewerLogic)
    const { configuredSessionIdKeys } = useValues(logsConfigLogic)
    const { copyLinkToLog } = useActions(logsViewerLogic)
    const { openLogDetails } = useActions(logDetailsModalLogic)
    const { openWithSeed } = useActions(logsMetricRuleQuickCreateLogic)
    const { startScrolling, stopScrolling } = useCellScrollControls({ id, cellKey: 'message' })
    const sessionId = getSessionIdFromLogAttributes(log.attributes, log.resource_attributes, configuredSessionIdKeys)
    const metricRulesEnabled = useFeatureFlag(LogsFeatureFlagKeys.metricRules)
    const metricsEditorDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Metrics,
        AccessControlLevel.Editor
    )
    const tracingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Tracing,
        AccessControlLevel.Viewer
    )

    return (
        <div
            className={cn(
                'absolute right-2 top-1/2 -translate-y-1/2',
                'flex items-center gap-1',
                'opacity-0 group-hover:opacity-100 transition-opacity'
            )}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
        >
            <FABGroup>
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={<IconExpand45 />}
                    onClick={(e) => {
                        e.preventDefault()
                        openLogDetails(log)
                    }}
                    tooltip="View log details"
                    className="text-muted"
                    data-attr="logs-viewer-view-details"
                />
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={<IconBrackets />}
                    onClick={(e) => {
                        e.preventDefault()
                        onTogglePrettify?.(log)
                    }}
                    active={isPrettified}
                    tooltip={isPrettified ? 'Collapse JSON' : 'Prettify JSON'}
                    aria-label={isPrettified ? 'Collapse JSON' : 'Prettify JSON'}
                    className={cn(isPrettified ? 'text-brand-blue' : 'text-muted')}
                    disabledReason={log.parsedBody === null ? 'Log body is not valid JSON' : undefined}
                />
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={pinned ? <IconPinFilled /> : <IconPin />}
                    onClick={(e) => {
                        e.preventDefault()
                        onTogglePin(log)
                    }}
                    tooltip={pinned ? 'Unpin log' : 'Pin log'}
                    aria-label={pinned ? 'Unpin log' : 'Pin log'}
                    className={cn(pinned ? 'text-warning' : 'text-muted')}
                />
                <CopyLogButton log={log} noPadding className="text-muted" />
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={<IconLink />}
                    onClick={(e) => {
                        e.preventDefault()
                        copyLinkToLog(log.uuid)
                    }}
                    tooltip="Copy link to log"
                    aria-label="Copy link to log"
                    className="text-muted"
                    data-attr="logs-viewer-copy-link"
                />
                <LogContextSelector log={log} noPadding />
                {log.trace_id && !tracingDisabledReason && (
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconListTree />}
                        to={traceUrl({ traceId: log.trace_id, spanId: log.span_id || null, ts: log.timestamp })}
                        tooltip="View trace"
                        aria-label="View trace"
                        className="text-muted"
                        data-attr="logs-viewer-view-trace"
                    />
                )}
                {metricRulesEnabled && (
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconGraph />}
                        onClick={(e) => {
                            e.preventDefault()
                            openWithSeed(buildMetricRuleSeedFromLog(log))
                        }}
                        tooltip="Create log-based metric"
                        aria-label="Create log-based metric"
                        className="text-muted"
                        data-attr="logs-viewer-create-metric-rule"
                        disabledReason={metricsEditorDisabledReason ?? undefined}
                    />
                )}
                {sessionId && (
                    <ViewRecordingButton
                        sessionId={sessionId}
                        timestamp={log.timestamp}
                        size="xsmall"
                        openPlayerIn={RecordingPlayerType.Modal}
                        iconOnly
                        noPadding
                        className="text-muted"
                        data-attr="logs-viewer-view-recording"
                    />
                )}
            </FABGroup>

            {showScrollButtons && (
                <FABGroup>
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconChevronLeft />}
                        aria-label="Scroll left"
                        onMouseDown={(e) => {
                            e.preventDefault()
                            startScrolling('left')
                        }}
                        onMouseUp={stopScrolling}
                        onMouseLeave={stopScrolling}
                        className="text-muted"
                    />
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconChevronRight />}
                        aria-label="Scroll right"
                        onMouseDown={(e) => {
                            e.preventDefault()
                            startScrolling('right')
                        }}
                        onMouseUp={stopScrolling}
                        onMouseLeave={stopScrolling}
                        className="text-muted"
                    />
                </FABGroup>
            )}
        </div>
    )
}
