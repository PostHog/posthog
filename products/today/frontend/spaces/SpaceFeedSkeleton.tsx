import { Card, Separator, Skeleton, cn } from '@posthog/quill'

const CARD_FADES = [
    { wide: true, className: undefined },
    { wide: false, className: 'opacity-70' },
    { wide: true, className: 'opacity-40' },
    { wide: false, className: 'opacity-15' },
]

const LIST_GROUPS = [
    { className: undefined, widths: ['w-2/5', 'w-3/5', 'w-1/3'] },
    { className: 'opacity-50', widths: ['w-1/2', 'w-2/5', 'w-1/4'] },
]

export function SpaceFeedSkeleton({ listRows }: { listRows: boolean }): JSX.Element {
    if (listRows) {
        return (
            <div aria-hidden className="flex flex-col">
                {LIST_GROUPS.map((group, groupIndex) => (
                    <div key={groupIndex} className={cn('flex flex-col', group.className)}>
                        <div className="px-2 pt-3 pb-0.5">
                            <Skeleton className="h-2.5 w-14" />
                        </div>
                        {group.widths.map((width) => (
                            <div key={width} className="flex h-8 items-center gap-2 px-2">
                                <Skeleton className="size-3.5 shrink-0 rounded-sm" />
                                <Skeleton className={cn('h-3.5', width)} />
                                <Skeleton className="ml-auto h-4 w-14 shrink-0 rounded-full" />
                                <Skeleton className="size-4 shrink-0 rounded-full" />
                                <Skeleton className="h-3 w-6 shrink-0" />
                            </div>
                        ))}
                    </div>
                ))}
            </div>
        )
    }
    return (
        <div aria-hidden className="flex flex-col">
            <div className="flex items-center gap-3 pt-5 pb-2">
                <Separator className="flex-1" />
                <Skeleton className="h-3 w-12" />
                <Separator className="flex-1" />
            </div>
            {CARD_FADES.map((card, index) => (
                <Card key={index} size="sm" className={cn('my-1.5 gap-0 rounded-xl px-4 pt-3.5 pb-3', card.className)}>
                    <div className="flex items-start gap-3">
                        <Skeleton className={cn('h-4', card.wide ? 'w-3/5' : 'w-2/5')} />
                        <Skeleton className="ml-auto h-5 w-16 shrink-0 rounded-full" />
                    </div>
                    <div className="mt-2 flex flex-col gap-1.5">
                        <Skeleton className="h-3 w-full" />
                        <Skeleton className={cn('h-3', card.wide ? 'w-1/2' : 'w-3/4')} />
                    </div>
                    <div className="mt-3 flex items-center gap-2">
                        <Skeleton className="size-5 rounded-full" />
                        <Skeleton className="h-3 w-24" />
                    </div>
                </Card>
            ))}
        </div>
    )
}
