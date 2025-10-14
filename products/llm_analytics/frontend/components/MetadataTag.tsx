import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

interface MetadataTagProps {
    children: React.ReactNode
    label: string
    textToCopy?: string
}

export function MetadataTag({ children, label, textToCopy }: MetadataTagProps): JSX.Element {
    let wrappedChildren: React.ReactNode = children
    if (typeof textToCopy === 'string' && typeof children === 'string') {
        wrappedChildren = (
            <CopyToClipboardInline iconSize="xsmall" description={textToCopy} tooltipMessage={label}>
                {children}
            </CopyToClipboardInline>
        )
    } else {
        wrappedChildren = <Tooltip title={label}>{children}</Tooltip>
    }

    return <LemonTag className="bg-surface-primary cursor-default">{wrappedChildren}</LemonTag>
}
