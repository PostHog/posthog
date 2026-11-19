// PROTOTYPE (branch prototype/sending-limits-ux): a note to the reviewer, not product copy. Never merge.
import { ReactNode } from 'react'

export function PrototypeNote({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="border border-dashed rounded px-3 py-2 text-xs text-secondary">
            <strong>Prototype note:</strong> {children}
        </div>
    )
}
