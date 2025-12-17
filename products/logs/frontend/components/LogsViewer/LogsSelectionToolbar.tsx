import { useActions, useValues } from 'kea'

import { IconCopy, IconDownload } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { logsViewerLogic } from './logsViewerLogic'

export function LogsSelectionToolbar(): JSX.Element | null {
    const { isSelectionActive, selectedCount } = useValues(logsViewerLogic)
    const { copySelectedLogs, exportSelectedAsJson, exportSelectedAsCsv } = useActions(logsViewerLogic)

    if (!isSelectionActive) {
        return null
    }

    return (
        <div className="flex items-center gap-2 px-2 py-1 bg-primary-highlight rounded border border-primary text-sm flex-wrap">
            <span className="font-medium">{selectedCount} selected</span>
            <LemonButton size="xsmall" icon={<IconCopy />} onClick={copySelectedLogs}>
                Copy
            </LemonButton>
            <LemonMenu
                items={[
                    { label: 'Export as JSON', onClick: exportSelectedAsJson },
                    { label: 'Export as CSV', onClick: exportSelectedAsCsv },
                ]}
            >
                <LemonButton size="xsmall" icon={<IconDownload />}>
                    Export
                </LemonButton>
            </LemonMenu>
        </div>
    )
}
