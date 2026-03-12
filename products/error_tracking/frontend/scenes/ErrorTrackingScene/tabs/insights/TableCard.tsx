import { LemonSkeleton } from '@posthog/lemon-ui'

export function TableCard({
    title,
    description,
    loading,
    children,
}: {
    title: string
    description: string
    loading?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="border rounded-lg bg-surface-primary flex flex-col min-h-80">
            <div className="px-4 pt-3 pb-1 shrink-0">
                <h3 className="font-semibold text-sm m-0">{title}</h3>
                <p className="text-xs text-secondary m-0">{description}</p>
            </div>
            <div className="flex-1 min-h-0 overflow-auto px-2 pb-2">
                {loading ? (
                    <div className="space-y-3 p-2">
                        {Array.from({ length: 5 }).map((_, i) => (
                            <div key={i} className="flex items-center gap-3">
                                <LemonSkeleton className="h-5 flex-1" />
                                <LemonSkeleton className="h-5 w-20" />
                            </div>
                        ))}
                    </div>
                ) : (
                    children
                )}
            </div>
        </div>
    )
}
