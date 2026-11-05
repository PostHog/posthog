import type { ReactNode } from 'react'

import { IconCheck, IconChevronDown } from '@posthog/icons'

export type MockStepState = 'done' | 'current' | 'next'

export function MockTimelineStep({
    title,
    summary,
    when,
    state,
    children,
}: {
    title: string
    summary: string
    when?: string
    state: MockStepState
    children?: ReactNode
}): JSX.Element {
    const header = (
        <>
            <span className="InboxMockup__stepTitle">{title}</span>
            <span className="InboxMockup__muted min-w-0 truncate">{summary}</span>
            <span className="InboxMockup__muted ms-auto shrink-0 tabular-nums">{when}</span>
            {children && <IconChevronDown className="InboxMockup__disclosureChevron" aria-hidden />}
        </>
    )
    return (
        <li className="InboxMockup__step" data-state={state}>
            <span className="InboxMockup__stepMarker" aria-hidden>
                {state === 'done' && <IconCheck />}
            </span>
            {children ? (
                <details open={state === 'current'}>
                    <summary className="InboxMockup__stepHeader">{header}</summary>
                    <div className="InboxMockup__stepPanel">{children}</div>
                </details>
            ) : (
                <div className="InboxMockup__stepHeader">{header}</div>
            )}
        </li>
    )
}
