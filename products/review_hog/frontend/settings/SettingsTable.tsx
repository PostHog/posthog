import { SETTINGS_HEADER } from './settingsRowClasses'

/** A table of rows with a project value and the viewer's own value, under a three-column header. */
export function SettingsTable({
    firstColumn = 'Setting',
    children,
}: {
    firstColumn?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="@container overflow-hidden rounded border border-primary bg-surface-primary">
            <div className={SETTINGS_HEADER}>
                <span>{firstColumn}</span>
                <span>Project</span>
                <span>Mine</span>
            </div>
            {children}
        </div>
    )
}
