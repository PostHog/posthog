import { ReactNode } from 'react'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'

import { NotebookBtw } from './NotebookBtw'
import type { NotebookBtwSession } from './notebookBtwLogic'

export function NotebookBtwLayout({
    children,
    session,
    onClose,
}: {
    children: ReactNode
    session: NotebookBtwSession | null
    onClose: () => void
}): JSX.Element {
    // Leave room for the notebook beside the conversation, including inside another side panel.
    const { ref, size } = useResizeBreakpoints({ 0: 'modal', 900: 'sidebar' })

    return (
        <div ref={ref} className="flex min-w-0 flex-1 gap-4">
            <div className="min-w-0 flex-1">{children}</div>
            {session && <NotebookBtw session={session} onClose={onClose} presentation={size} />}
        </div>
    )
}
