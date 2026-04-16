import { useActions } from 'kea'
import posthog from 'posthog-js'

import { IconList } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import { logDetailsModalLogic } from '../LogDetailsModal/logDetailsModalLogic'
import { logsViewerModalLogic } from '../LogsViewerModal/logsViewerModalLogic'
import { buildContextFilters, getAvailableContexts } from './logContextUtils'

interface LogContextSelectorProps {
    log: ParsedLogMessage
    size?: 'xsmall' | 'small'
    noPadding?: boolean
}

export function LogContextSelector({ log, size = 'xsmall', noPadding }: LogContextSelectorProps): JSX.Element | null {
    const { openLogsViewerModal } = useActions(logsViewerModalLogic)
    const { closeLogDetails } = useActions(logDetailsModalLogic)

    const contexts = getAvailableContexts(log)
    if (contexts.length === 0) {
        return null
    }

    return (
        <LemonMenu
            items={contexts.map((ctx) => ({
                label: ctx.label,
                tooltip: ctx.description,
                onClick: () => {
                    posthog.capture('logs context viewed', { context_type: ctx.type })
                    closeLogDetails()
                    const filters = buildContextFilters(log, ctx.type)
                    openLogsViewerModal({
                        id: `context-${log.uuid}-${ctx.type}`,
                        fullScreen: false,
                        initialFilters: filters,
                    })
                },
            }))}
        >
            <LemonButton
                size={size}
                icon={<IconList />}
                tooltip="View in context"
                aria-label="View in context"
                noPadding={noPadding ?? size === 'xsmall'}
                className="text-muted"
                data-attr="logs-viewer-context-selector"
            />
        </LemonMenu>
    )
}
