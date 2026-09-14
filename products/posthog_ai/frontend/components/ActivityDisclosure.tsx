import type { ReactNode } from 'react'

import { CollapsiblePrimitive, CollapsiblePrimitiveContent } from 'lib/ui/Collapsible/lib/CollapsiblePrimitive'

export function ActivityDisclosure({
    open,
    id,
    children,
}: {
    open: boolean
    id?: string
    children: ReactNode
}): JSX.Element {
    return (
        <CollapsiblePrimitive open={open}>
            <CollapsiblePrimitiveContent
                id={id}
                className="transition-[height,opacity] duration-150 ease-out opacity-100 data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 motion-reduce:transition-none"
            >
                {children}
            </CollapsiblePrimitiveContent>
        </CollapsiblePrimitive>
    )
}
