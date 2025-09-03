import { useState } from 'react'

import { IconCommit } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover/Popover'

export interface ReleaseTagProps {
    title: string
    overlay: JSX.Element
}

export function ReleaseTag({ title, overlay }: ReleaseTagProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <Popover
            visible={isOpen}
            overlay={overlay}
            placement="right"
            padded={false}
            showArrow
            onMouseEnterInside={() => setIsOpen(true)}
            onMouseLeaveInside={() => setIsOpen(false)}
        >
            <span
                className="inline-flex align-middle"
                onMouseEnter={() => setIsOpen(true)}
                onMouseLeave={() => setIsOpen(false)}
            >
                <LemonTag
                    className="bg-fill-primary"
                    onMouseEnter={() => setIsOpen(true)}
                    onMouseLeave={() => setIsOpen(false)}
                >
                    <IconCommit className="text-sm text-secondary" />
                    <span>{title}</span>
                </LemonTag>
            </span>
        </Popover>
    )
}
