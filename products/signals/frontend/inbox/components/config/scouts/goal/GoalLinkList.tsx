import type { ReactNode } from 'react'

import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface GoalLink {
    key: string
    icon: ReactNode
    label: string
    to?: string
    external?: boolean
    dataAttr?: string
}

export function GoalLinkList({
    links,
    layout = 'row',
}: {
    links: GoalLink[]
    layout?: 'row' | 'column'
}): JSX.Element | null {
    if (!links.length) {
        return null
    }
    return (
        <ul
            className={cn(
                'm-0 flex list-none p-0 text-xs',
                layout === 'row' ? 'flex-wrap gap-x-5 gap-y-1.5' : 'flex-col gap-1.5'
            )}
        >
            {links.map((link) => (
                <li key={link.key} className="flex min-w-0 max-w-full items-center gap-1.5">
                    <span className="flex shrink-0 text-tertiary [&_svg]:size-3.5">{link.icon}</span>
                    {link.to ? (
                        <Link
                            to={link.to}
                            target={link.external ? '_blank' : undefined}
                            subtle
                            className="truncate"
                            data-attr={link.dataAttr}
                        >
                            {link.label}
                        </Link>
                    ) : (
                        <span className="truncate text-secondary">{link.label}</span>
                    )}
                </li>
            ))}
        </ul>
    )
}
