import { JSONViewer } from 'lib/components/JSONViewer'

import { PropertyFilterType } from '~/types'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import { LogAttributes } from './LogAttributes'

export interface LogDetailsTabContentProps {
    log: ParsedLogMessage
}

export function LogDetailsTabContent({ log }: LogDetailsTabContentProps): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <LogAttributes
                attributes={log.attributes}
                type={PropertyFilterType.LogAttribute}
                logUuid={log.uuid}
                title="Log attributes"
            />
            <LogAttributes
                attributes={log.resource_attributes as Record<string, string>}
                type={PropertyFilterType.LogResourceAttribute}
                logUuid={log.uuid}
                title="Resource attributes"
            />
            <h3 className="text-sm font-semibold text-muted">Log Message</h3>
            <div className="p-3 bg-bg-light rounded border border-border">
                {log.parsedBody && typeof log.parsedBody === 'object' ? (
                    <JSONViewer src={log.parsedBody as object} collapsed={2} />
                ) : (
                    <span className="font-mono text-sm whitespace-pre-wrap break-all">{log.cleanBody}</span>
                )}
            </div>
        </div>
    )
}
