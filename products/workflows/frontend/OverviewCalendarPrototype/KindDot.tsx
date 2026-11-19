// PROTOTYPE (throwaway): the color of a messaging type, matching its type tag.
import clsx from 'clsx'

import { EntryKind } from './prototypeData'

const KIND_COLOR: Record<EntryKind, string> = {
    broadcast: 'bg-info-foreground',
    workflow: 'bg-completed-foreground',
    transactional: 'bg-muted-foreground',
}

export function KindDot({ kind, className }: { kind: EntryKind; className?: string }): JSX.Element {
    return (
        <span aria-hidden className={clsx('inline-block size-2 shrink-0 rounded-full', KIND_COLOR[kind], className)} />
    )
}
