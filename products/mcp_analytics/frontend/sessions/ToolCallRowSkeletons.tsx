import { LemonSkeleton } from '@posthog/lemon-ui'

import { MCPToolCallRowShell } from './MCPToolCallRowShell'

export function ToolCallRowSkeletons({ count }: { count: number }): JSX.Element {
    return (
        <ol className="flex flex-col gap-2 list-none pl-0" aria-hidden>
            {Array.from({ length: count }, (_, i) => (
                <MCPToolCallRowShell key={i}>
                    <div className="flex h-4 items-center justify-between gap-2">
                        <LemonSkeleton className="h-3 w-32" />
                        <LemonSkeleton className="h-3 w-20" />
                    </div>
                    <div className="flex h-4 items-center pl-5">
                        <LemonSkeleton className="h-3 w-3/5" />
                    </div>
                </MCPToolCallRowShell>
            ))}
        </ol>
    )
}
