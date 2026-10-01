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
    Heading,
    Skeleton,
} from '@posthog/quill'

import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { SpaceLoopBuilderComposer } from './SpaceLoopBuilderComposer'
import { SpaceLoopsFilterBar } from './SpaceLoopsFilterBar'
import { spaceLoopsLogic } from './spaceLoopsLogic'
import { SpaceLoopsTable } from './SpaceLoopsTable'
import { SpaceLoopTemplates } from './SpaceLoopTemplates'

/** A space's Loops tab, laid out like PostHog Desktop's: the loops, templates, then the loop builder. */
export function SpaceLoops({ id }: { id: string }): JSX.Element {
    const { loops, loopsLoading, loopsUnavailable, space } = useValues(spaceLoopsLogic({ id }))
    const { loadLoops, focusBuilder } = useActions(spaceLoopsLogic({ id }))

    return (
        <div className="@container mx-auto flex w-full max-w-5xl flex-col gap-6 pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Heading size="xl" render={<h2 />}>
                    Loops
                </Heading>
                <Button variant="primary" onClick={focusBuilder} data-attr="today-space-loop-new">
                    <IconPlus />
                    New loop
                </Button>
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
                <Empty className="border border-dashed py-10">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconRefresh />
                        </EmptyMedia>
                        <EmptyTitle>
                            {space ? `Create a loop for ${spaceLabel(space)}` : 'Create a loop for this space'}
                        </EmptyTitle>
                        <EmptyDescription>
                            Describe what to automate below, or start from a template. An agent sets up the loop with
                            you, then it runs in the cloud on its own and posts each run here.
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : (
                <div className="flex flex-col gap-3">
                    <SpaceLoopsFilterBar id={id} />
                    <SpaceLoopsTable id={id} />
                </div>
            )}
            <SpaceLoopTemplates id={id} />
            <SpaceLoopBuilderComposer id={id} />
        </div>
    )
}
