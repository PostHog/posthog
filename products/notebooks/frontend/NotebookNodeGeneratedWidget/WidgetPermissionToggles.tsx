import { LemonCheckbox } from '@posthog/lemon-ui'

import type { WidgetPermissions } from './widgetPermissions'

export function WidgetPermissionToggles({
    disabled,
    onChange,
    value,
}: {
    disabled?: boolean
    onChange: (permissions: WidgetPermissions) => void
    value: WidgetPermissions
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <LemonCheckbox
                bordered
                fullWidth
                checked={value.notebookData}
                disabled={disabled}
                onChange={(notebookData) => onChange({ ...value, notebookData })}
                label={
                    <span className="flex flex-col">
                        <span>Notebook dataframes</span>
                        <span className="text-xs font-normal text-muted">
                            Read completed SQL and Python results in this notebook.
                        </span>
                    </span>
                }
            />
            <LemonCheckbox
                bordered
                fullWidth
                checked={value.hogqlQueries}
                disabled={disabled}
                onChange={(hogqlQueries) => onChange({ ...value, hogqlQueries })}
                label={
                    <span className="flex flex-col">
                        <span>HogQL queries</span>
                        <span className="text-xs font-normal text-muted">
                            Query any project data the person viewing the widget can access.
                        </span>
                    </span>
                }
            />
            <LemonCheckbox
                bordered
                fullWidth
                checked={value.toolCalls}
                disabled={disabled}
                onChange={(toolCalls) => onChange({ ...value, toolCalls })}
                label={
                    <span className="flex flex-col">
                        <span>PostHog tool calls</span>
                        <span className="text-xs font-normal text-muted">
                            Read or change PostHog with tools available to the viewer. Suspicious use is flagged before
                            the widget runs.
                        </span>
                    </span>
                }
            />
        </div>
    )
}
