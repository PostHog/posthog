import { IconInfo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SETTINGS_ROW } from './settingsRowClasses'

/**
 * One row of a settings table: the setting, the project column, and the viewer's own column. On a
 * narrow container the columns stack and each one gets its label back.
 */
export function SettingRow({
    title,
    description,
    info,
    project,
    mine,
}: {
    title: string
    description: string
    /** Conditions a reader does not need to make the choice, shown on demand next to the title. */
    info?: string
    project: JSX.Element
    mine: JSX.Element
}): JSX.Element {
    return (
        <div className={`${SETTINGS_ROW} items-center`}>
            <div className="flex min-w-0 flex-col gap-0.5">
                <span className="flex items-center gap-1 text-sm font-semibold">
                    {title}
                    {info && (
                        <LemonButton
                            size="xsmall"
                            noPadding
                            icon={<IconInfo />}
                            tooltip={info}
                            aria-label={`More about: ${title}`}
                        />
                    )}
                </span>
                <span className="text-xs text-secondary">{description}</span>
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="text-xs text-secondary @min-[48rem]:hidden">Project:</span>
                {project}
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="text-xs text-secondary @min-[48rem]:hidden">Mine:</span>
                {mine}
            </div>
        </div>
    )
}
