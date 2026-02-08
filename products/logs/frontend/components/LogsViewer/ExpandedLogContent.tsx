import { PropertyFilterType } from '~/types'

import { LogAttributes } from 'products/logs/frontend/components/LogsViewer/LogAttributes'
import { ParsedLogMessage } from 'products/logs/frontend/types'

export interface ExpandedLogContentProps {
    log: ParsedLogMessage
}

export function ExpandedLogContent({ log }: ExpandedLogContentProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2 p-2 bg-primary border-t border-border">
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
