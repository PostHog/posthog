import { ReactNode } from 'react'

/**
 * One setting in the Autonomy section: a title, one line of context, and one control. Every row
 * has the same shape, so a reader scans the left column for the setting and the right column for
 * its value. The control sits right of the text where the width allows and wraps below it in a
 * narrow scene. Dependent settings that the control reveals render indented under the row.
 */
export function AutonomySettingRow({
    title,
    description,
    control,
    children,
}: {
    title: string
    description?: ReactNode
    control?: ReactNode
    children?: ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3 py-3">
            {/* basis-48 leaves room for a switch beside the text in the 320px legacy rail. */}
            <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <div className="flex min-w-0 flex-1 basis-48 flex-col gap-0.5">
                    <span className="text-sm font-medium text-default">{title}</span>
                    {description && <p className="m-0 text-xs leading-snug text-secondary">{description}</p>}
                </div>
                {/* max-w-full caps a control wider than the row, so a full-width segmented button compresses instead of overflowing. */}
                {control && <div className="flex max-w-full shrink-0 items-center gap-1">{control}</div>}
            </div>
            {children && (
                <div className="ml-0.5 flex flex-col divide-y divide-primary border-l-2 border-primary pl-4 [&>*:first-child]:pt-0 [&>*:last-child]:pb-0">
                    {children}
                </div>
            )}
        </div>
    )
}
