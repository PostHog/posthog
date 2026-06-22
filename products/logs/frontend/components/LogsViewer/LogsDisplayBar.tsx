import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { logsViewerConfigLogic } from './config/logsViewerConfigLogic'
import { LogsViewerToolbar, LogsViewerToolbarProps } from './LogsViewerToolbar'

/**
 * Bottom toolbar for the field-rail layout — the "operate on the data" controls: the rail toggle plus
 * the result-view controls (sort, wrap, timezone, export, fullscreen, count). Sits below the sparkline,
 * next to the table it affects. None of these re-run the query; they only change how results render.
 */
export const LogsDisplayBar = (props: LogsViewerToolbarProps): JSX.Element => {
    const { fieldRailCollapsed } = useValues(logsViewerConfigLogic)
    const { setFieldRailCollapsed } = useActions(logsViewerConfigLogic)

    return (
        <div className="flex items-start gap-2">
            <LemonButton
                size="small"
                icon={fieldRailCollapsed ? <IconChevronRight /> : <IconChevronLeft />}
                onClick={() => setFieldRailCollapsed(!fieldRailCollapsed)}
                aria-label={fieldRailCollapsed ? 'Show filters' : 'Hide filters'}
            >
                {fieldRailCollapsed ? 'Show filters' : 'Hide filters'}
            </LemonButton>
            <div className="flex-1 min-w-0">
                <LogsViewerToolbar {...props} />
            </div>
        </div>
    )
}
