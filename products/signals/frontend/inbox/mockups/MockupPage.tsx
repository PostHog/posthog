import './InboxMockups.scss'

import type { ReactNode } from 'react'

import 'scenes/project-homepage/today/Today.scss'

export function MockupPage({
    width = 'narrow',
    children,
}: {
    width?: 'narrow' | 'wide'
    children: ReactNode
}): JSX.Element {
    return (
        <div className="InboxMockup Today">
            <div className="InboxMockup__page Today__page" data-width={width} data-quill>
                {children}
            </div>
        </div>
    )
}
