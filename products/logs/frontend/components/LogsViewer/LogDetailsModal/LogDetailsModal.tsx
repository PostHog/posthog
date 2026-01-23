import { useActions, useValues } from 'kea'

import { IconCopy, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonModal, LemonTabs } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { TZLabel } from 'lib/components/TZLabel'
import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { LogDetailsTabContent } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal/Tabs/Details/LogDetailsTab'

import { logsViewerLogic } from '../logsViewerLogic'
import { LogComments } from './LogComments'
import { LogExploreAI } from './Tabs/ExploreWithAI'
import { LogDetailsTab, logDetailsModalLogic } from './logDetailsModalLogic'

const SEVERITY_COLORS: Record<string, string> = {
    trace: 'bg-muted-alt',
    debug: 'bg-muted',
    info: 'bg-brand-blue',
    warn: 'bg-warning',
    error: 'bg-danger',
    fatal: 'bg-danger-dark',
}

// Deep parse all string fields that look like JSON
function parseJsonFields(obj: unknown): unknown {
    if (typeof obj === 'string') {
        try {
            const parsed = JSON.parse(obj)
            return parseJsonFields(parsed)
        } catch {
            return obj
        }
    }
    if (Array.isArray(obj)) {
        return obj.map(parseJsonFields)
    }
    if (obj !== null && typeof obj === 'object') {
        const result: Record<string, unknown> = {}
        for (const [key, value] of Object.entries(obj)) {
            result[key] = parseJsonFields(value)
        }
        return result
    }
    return obj
}

interface LogDetailsModalProps {
    timezone: string
}

export function LogDetailsModal({ timezone }: LogDetailsModalProps): JSX.Element | null {
    const { isLogDetailsOpen, selectedLog, jsonParseAllFields, activeTab } = useValues(logDetailsModalLogic)
    const { closeLogDetails, setJsonParseAllFields, setActiveTab } = useActions(logDetailsModalLogic)
    const { addFilter, copyLinkToLog } = useActions(logsViewerLogic)

    const handleApplyFilter = (key: string, value: string, attributeType: 'log' | 'resource'): void => {
        const filterType =
            attributeType === 'resource' ? PropertyFilterType.LogResourceAttribute : PropertyFilterType.LogAttribute
        addFilter(key, value, PropertyOperator.Exact, filterType)
        closeLogDetails()
    }

    if (!selectedLog) {
        return null
    }

    const severityColor = SEVERITY_COLORS[selectedLog.severity_text] ?? 'bg-muted-3000'
    const displayData = jsonParseAllFields
        ? (parseJsonFields(selectedLog.originalLog) as object)
        : selectedLog.originalLog

    return (
        <LemonModal
            title="Log details"
            isOpen={isLogDetailsOpen}
            onClose={closeLogDetails}
            simple
            overlayClassName="backdrop-blur-none bg-transparent flex items-stretch justify-end pr-16 py-4 h-screen"
            className="m-0! max-w-3xl w-[50vw] min-h-full"
            hideCloseButton
        >
            <div className="flex flex-col h-full">
                <LemonModal.Header className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                        <h3>Log details</h3>
                        <div className="flex items-center gap-1">
                            <LemonButton
                                size="xsmall"
                                icon={<IconCopy />}
                                onClick={() => void copyToClipboard(selectedLog.body, 'log message')}
                                tooltip="Copy log message"
                                aria-label="Copy log message"
                                data-attr="logs-viewer-copy-message"
                            />
                            <LemonButton
                                size="xsmall"
                                icon={<IconLink />}
                                onClick={() => copyLinkToLog(selectedLog.uuid)}
                                tooltip="Copy link to log"
                                aria-label="Copy link to log"
                                data-attr="logs-viewer-copy-link"
                            />
                            <LemonButton
                                size="xsmall"
                                icon={<IconX />}
                                onClick={closeLogDetails}
                                tooltip="Close"
                                aria-label="Close"
                            />
                        </div>
                    </div>
                    <div className="flex items-center gap-6">
                        <div className="flex items-center gap-2">
                            <span className="text-muted text-xs font-semibold uppercase">Timestamp</span>
                            <span className="text-xs font-mono">
                                <TZLabel
                                    time={selectedLog.timestamp}
                                    formatDate="YYYY-MM-DD"
                                    formatTime="HH:mm:ss.SSS"
                                    displayTimezone={timezone}
                                    timestampStyle="absolute"
                                />
                            </span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-muted text-xs font-semibold uppercase">Severity</span>
                            <div className="flex items-center gap-1.5">
                                <div className={`w-2 h-2 rounded-full ${severityColor}`} />
                                <span className="font-mono text-xs">{selectedLog.severity_text.toUpperCase()}</span>
                            </div>
                        </div>
                    </div>
                </LemonModal.Header>
                <LemonModal.Content>
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(key) => setActiveTab(key as LogDetailsTab)}
                        tabs={[
                            {
                                key: 'details',
                                label: 'Details',
                                content: <LogDetailsTabContent log={selectedLog} />,
                            },
                            {
                                key: 'raw',
                                label: 'Raw',
                                content: (
                                    <div className="flex flex-col gap-2">
                                        <div className="flex items-center">
                                            <LemonCheckbox
                                                checked={jsonParseAllFields}
                                                onChange={setJsonParseAllFields}
                                                label="JSON parse all fields"
                                                size="small"
                                            />
                                        </div>
                                        <div className="p-2 bg-bg-light rounded overflow-auto">
                                            <JSONViewer src={displayData} collapsed={2} sortKeys />
                                        </div>
                                    </div>
                                ),
                            },
                            {
                                key: 'explore-ai',
                                label: 'Explore with AI',
                                content: (
                                    <LogExploreAI
                                        logUuid={selectedLog.uuid}
                                        logTimestamp={selectedLog.timestamp}
                                        onApplyFilter={handleApplyFilter}
                                    />
                                ),
                            },
                            {
                                key: 'comments',
                                label: 'Comments',
                                content: <LogComments log={selectedLog} />,
                            },
                        ]}
                    />
                </LemonModal.Content>
            </div>
        </LemonModal>
    )
}
