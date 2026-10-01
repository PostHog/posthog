import { useActions, useValues } from 'kea'

import { IconPlus, IconRefresh } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Table,
    TableBody,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { SpaceLoopRow } from './SpaceLoopRow'
import { spaceLoopsLogic } from './spaceLoopsLogic'

export function SpaceLoops({ id }: { id: string }): JSX.Element {
    const { loops, loopsLoading, loopsUnavailable } = useValues(spaceLoopsLogic({ id }))
    const { loadLoops, startLoopBuilder } = useActions(spaceLoopsLogic({ id }))

    const newLoopButton = (variant: 'primary' | 'outline', dataAttr: string): JSX.Element => (
        <Button variant={variant} onClick={startLoopBuilder} data-attr={dataAttr}>
            <IconPlus />
            New loop
        </Button>
    )

    return (
        <div className="@container mx-auto flex w-full max-w-5xl flex-col gap-4 pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Text size="sm" variant="muted">
                    Loops run an agent task on a schedule or when an event happens, and post each run to this space.
                </Text>
                {loops?.length ? newLoopButton('primary', 'today-space-loop-new') : null}
            </div>
            {loopsLoading && !loops ? (
                <div aria-hidden className="flex flex-col gap-px">
                    {[0, 1, 2].map((row) => (
                        <Skeleton key={row} className="h-12 w-full" />
                    ))}
                </div>
            ) : loopsUnavailable && !loops ? (
                <Empty className="py-12">
                    <EmptyHeader>
                        <EmptyTitle>Loops didn’t load</EmptyTitle>
                        <EmptyDescription>Check your connection and try again.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            loading={loopsLoading}
                            onClick={() => loadLoops()}
                            data-attr="today-space-loops-retry"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            ) : !loops?.length ? (
                <Empty className="py-12">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconRefresh />
                        </EmptyMedia>
                        <EmptyTitle>No loops in this space yet</EmptyTitle>
                        <EmptyDescription>
                            Describe what to automate, and an agent sets up the loop with you. It then runs in the cloud
                            without you.
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>{newLoopButton('outline', 'today-space-loop-new-empty')}</EmptyContent>
                </Empty>
            ) : (
                <Table fullWidth>
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>Loop</TableHead>
                            <TableHead className="hidden @lg:table-cell">Trigger</TableHead>
                            <TableHead className="hidden @md:table-cell">Last run</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loops.map((loop) => (
                            <SpaceLoopRow key={loop.id} loop={loop} />
                        ))}
                    </TableBody>
                </Table>
            )}
        </div>
    )
}
