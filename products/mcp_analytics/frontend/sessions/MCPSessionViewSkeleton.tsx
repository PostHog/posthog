import { LemonSkeleton } from '@posthog/lemon-ui'

import { ToolCallRowSkeletons } from './ToolCallRowSkeletons'

export function MCPSessionViewSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col h-full min-h-0" aria-busy>
            <header className="flex flex-col gap-2 shrink-0 border-b border-primary px-3 pt-3 pb-2">
                <div className="flex items-center gap-2">
                    <LemonSkeleton.Circle className="h-9 w-9" />
                    <div className="flex flex-col flex-1 gap-1">
                        <LemonSkeleton className="h-4 w-40" />
                        <LemonSkeleton className="h-3 w-56" />
                    </div>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                    {['w-28', 'w-20', 'w-14', 'w-28'].map((width, i) => (
                        <LemonSkeleton key={i} className={`h-5 rounded-full ${width}`} />
                    ))}
                </div>
            </header>
            <section className="flex-1 min-h-0 overflow-hidden px-3 py-3">
                <ToolCallRowSkeletons count={4} />
            </section>
            <hr className="shrink-0 border-t border-primary my-0" />
            <footer className="shrink-0 px-3 py-3">
                <LemonSkeleton className="h-6 w-48" />
            </footer>
        </div>
    )
}
