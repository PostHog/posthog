import { Tooltip } from '@posthog/lemon-ui'

import { midEllipsis } from 'lib/utils/strings'

// Keeps the head and tail of an identifier visible, since keys often differ only at the ends.
export function TruncatedText({
    text,
    maxLength,
    className,
}: {
    text: string
    maxLength: number
    className?: string
}): JSX.Element {
    const display = midEllipsis(text, maxLength)

    if (display === text) {
        return <span className={className}>{text}</span>
    }

    return (
        <Tooltip title={text}>
            <span className={className}>{display}</span>
        </Tooltip>
    )
}
