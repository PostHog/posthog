import { ReactNode } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IssuePaneSectionName } from './IssuePaneSectionName'

export interface IssuePaneSectionHeaderProps {
    name: string
    open: boolean
    onToggle: () => void
    preview?: ReactNode
    /** Controls at the end of the strip. They sit beside the toggle, because a button cannot hold another. */
    trailing?: ReactNode
    dataAttr: string
}

export function IssuePaneSectionHeader({
    name,
    open,
    onToggle,
    preview,
    trailing,
    dataAttr,
}: IssuePaneSectionHeaderProps): JSX.Element {
    return (
        <div className="flex h-[2rem] w-full shrink-0 items-center gap-1 border-b pl-0.5 pr-2">
            <LemonButton
                size="xsmall"
                // LemonButton fills an expanded button like a pressed one. An open section is not pressed.
                className="min-w-0 flex-1 [&[aria-expanded=true]:not(:hover)]:bg-transparent!"
                icon={open ? <IconChevronDown /> : <IconChevronRight />}
                onClick={onToggle}
                aria-expanded={open}
                data-attr={dataAttr}
            >
                <span className="flex min-w-0 items-center gap-2">
                    <IssuePaneSectionName name={name} />
                    {preview ? (
                        <span className="min-w-0 truncate text-xs font-normal text-secondary">{preview}</span>
                    ) : null}
                </span>
            </LemonButton>
            {trailing}
        </div>
    )
}
