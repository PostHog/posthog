import { LemonTag } from '@posthog/lemon-ui'
import { cn } from 'lib/utils/css-classes'

export interface ErrorTagProps {
    label: string
    color: 'yellow' | 'red' | 'blue'
}

const tagColor = {
    yellow: 'bg-brand-yellow',
    red: 'bg-brand-red',
    blue: 'bg-brand-blue',
}

export function ErrorTag({ color, label }: ErrorTagProps): JSX.Element {
    return (
        <LemonTag
            size="small"
            className={cn(
                'font-semibold text-white border-gray-100/20 px-1 py-[0.1rem] text-[11px] rounded-sm inline',
                tagColor[color]
            )}
        >
            {label}
        </LemonTag>
    )
}
