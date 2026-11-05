import clsx from 'clsx'
import type { ReactNode } from 'react'

import { MessageTemplate } from '../messages/MessageTemplate'
import { useQuillThread } from './quill/quillThreadContext'
import { QuillWidgetCard } from './quill/QuillWidgetCard'

export interface WidgetCardProps {
    /** The scrolling body, e.g. a chart. Omit to show only the footer (a collapsed widget). */
    body?: ReactNode
    /** Height class for the body, e.g. `h-96`. The body scrolls past it. */
    bodyHeightClassName?: string
    footer: ReactNode
    danger?: boolean
}

/** The frame a product widget sits in inside the thread. Each skin draws it; the widget stays skin-agnostic. */
export function WidgetCard(props: WidgetCardProps): JSX.Element {
    return useQuillThread() ? <QuillWidgetCard {...props} /> : <LemonWidgetCard {...props} />
}

function LemonWidgetCard({ body, bodyHeightClassName, footer, danger = false }: WidgetCardProps): JSX.Element {
    return (
        <MessageTemplate
            type="ai"
            className="w-full"
            wrapperClassName="w-full"
            boxClassName={clsx('flex flex-col w-full', danger && 'border-danger')}
        >
            <div className="flex flex-col w-full">
                {body && <div className={clsx('flex flex-col overflow-auto', bodyHeightClassName)}>{body}</div>}
                <div className={clsx('flex flex-col', body && 'mt-2')}>{footer}</div>
            </div>
        </MessageTemplate>
    )
}
