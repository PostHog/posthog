import { useActions } from 'kea'

import { PropertyFilterType } from '~/types'

import { LogAttributes } from 'products/logs/frontend/components/LogsViewer/LogAttributes'
import { LogContextLinks } from 'products/logs/frontend/components/LogsViewer/LogContextLinks/LogContextLinks'
import { logDetailsModalLogic } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal/logDetailsModalLogic'
import { ParsedLogMessage } from 'products/logs/frontend/types'

export interface ExpandedLogContentProps {
    log: ParsedLogMessage
}

export function ExpandedLogContent({ log }: ExpandedLogContentProps): JSX.Element {
    const { openLogRelatedErrors } = useActions(logDetailsModalLogic)

    return (
        <div className="hotkey-block flex flex-col gap-2 p-2 bg-primary border-t border-border">
            <LogContextLinks
                log={log}
                surface="row"
                onOpenRelatedErrors={(scope) => openLogRelatedErrors(log, scope)}
            />
            <LogAttributes
                attributes={log.attributes}
                type={PropertyFilterType.LogAttribute}
                logUuid={log.uuid}
                title="Log attributes"
            />
            <LogAttributes
                attributes={(log.resource_attributes ?? {}) as Record<string, string>}
                type={PropertyFilterType.LogResourceAttribute}
                logUuid={log.uuid}
                title="Resource attributes"
            />
        </div>
    )
}
