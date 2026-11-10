import { useState } from 'react'

import type { ActivityToggleSectionProps } from '../ActivityPrimitives'
import { ThreadMarker } from './ThreadMarker'

export function QuillActivityToggleSection({
    title,
    summary,
    tooltip,
    children,
}: ActivityToggleSectionProps): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <ThreadMarker
            shimmer={false}
            open={open}
            onOpenChange={setOpen}
            body={
                <div className="min-w-0" data-not-quill>
                    {children}
                </div>
            }
        >
            <span className="min-w-0 truncate font-medium" title={tooltip}>
                {title}
            </span>
            {summary && <span className="min-w-0 truncate">{summary}</span>}
        </ThreadMarker>
    )
}
