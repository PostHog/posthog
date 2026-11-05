import type { ReactNode } from 'react'

import { IconChevronDown } from '@posthog/icons'

export function MockDisclosure({
    title,
    summary,
    defaultOpen = false,
    children,
}: {
    title: string
    summary: string
    defaultOpen?: boolean
    children: ReactNode
}): JSX.Element {
    return (
        <details className="InboxMockup__disclosure" open={defaultOpen}>
            <summary className="InboxMockup__disclosureTrigger">
                <span className="InboxMockup__disclosureTitle">{title}</span>
                <span className="InboxMockup__muted min-w-0 truncate">{summary}</span>
                <IconChevronDown className="InboxMockup__disclosureChevron" aria-hidden />
            </summary>
            <div className="InboxMockup__disclosurePanel">{children}</div>
        </details>
    )
}
