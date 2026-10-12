/**
 * One row of a settings table: the setting, the project column, and the viewer's own column. On a
 * narrow container the columns stack and each one gets its label back.
 */
export function SettingRow({
    title,
    description,
    project,
    mine,
}: {
    title: string
    description: string
    project: JSX.Element
    mine: JSX.Element
}): JSX.Element {
    return (
        <div className="grid grid-cols-1 items-center gap-2 border-t border-primary px-4 py-3 @min-[48rem]:grid-cols-[minmax(0,1fr)_minmax(0,14rem)_minmax(0,16rem)] @min-[48rem]:gap-3">
            <div className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-semibold">{title}</span>
                <span className="text-xs text-secondary">{description}</span>
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="text-xs text-secondary @min-[48rem]:hidden">Project:</span>
                {project}
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-1">
                <span className="text-xs text-secondary @min-[48rem]:hidden">Mine:</span>
                {mine}
            </div>
        </div>
    )
}
