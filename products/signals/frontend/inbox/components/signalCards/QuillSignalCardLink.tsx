import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

/** A link-out at the foot of a quill signal card, such as "View issue". Put a trailing icon last in `children`. */
export function QuillSignalCardLink({
    to,
    newTab = false,
    children,
    'data-attr': dataAttr,
}: {
    to: string
    newTab?: boolean
    children: React.ReactNode
    'data-attr'?: string
}): JSX.Element {
    return (
        <Button
            variant="link"
            size="sm"
            nativeButton={false}
            render={<LinkPrimitive to={to} target={newTab ? '_blank' : undefined} />}
            data-attr={dataAttr}
        >
            {children}
        </Button>
    )
}
