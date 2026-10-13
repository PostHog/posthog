import { IconInfo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

/**
 * One setting: what it is on the left, its control on the right. On a narrow container the control
 * wraps under the text.
 */
export function SettingRow({
    title,
    description,
    info,
    children,
}: {
    title: string
    description: string
    /** Conditions a reader does not need to make the choice, shown on demand next to the title. */
    info?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
            <div className="flex min-w-48 flex-1 flex-col gap-0.5">
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
            <div className="flex max-w-full min-w-0 items-center">{children}</div>
        </div>
    )
}
