import { ReactNode } from 'react'

export interface SuggestionsStatusNoticeProps {
    icon: ReactNode
    message: string
    extra?: ReactNode
}

export function SuggestionsStatusNotice({ icon, message, extra }: SuggestionsStatusNoticeProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded border border-primary bg-surface-primary px-3 py-2 text-sm">
            <span className="flex shrink-0 text-base text-secondary">{icon}</span>
            <span className="min-w-0 flex-1">{message}</span>
            {extra}
        </div>
    )
}
