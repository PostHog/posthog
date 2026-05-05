import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

interface MetadataTagProps {
    children: React.ReactNode
    label: string
    textToCopy?: string
    tooltipContent?: React.ReactNode
}

export function MetadataTag({ children, label, textToCopy, tooltipContent }: MetadataTagProps): JSX.Element {
    const isCopyable = typeof textToCopy === 'string' && typeof children === 'string'
    let wrappedChildren: React.ReactNode = children
    if (isCopyable) {
        wrappedChildren = (
            <CopyToClipboardInline iconSize="xsmall" description={textToCopy} tooltipMessage={label}>
                {children}
            </CopyToClipboardInline>
        )
    } else {
        wrappedChildren = <Tooltip title={tooltipContent ?? label}>{children}</Tooltip>
    }

    const cursorClass = isCopyable ? 'cursor-default' : 'cursor-help'
    return <LemonTag className={`bg-surface-primary ${cursorClass}`}>{wrappedChildren}</LemonTag>
}
