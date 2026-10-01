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
    Text,
} from '@posthog/quill'

import { SpaceSettingsSection } from '../SpaceSettingsSection'
import { SpaceLoopBuilderComposer } from './SpaceLoopBuilderComposer'
import { SpaceLoopsFilterBar } from './SpaceLoopsFilterBar'
import { SpaceLoopsList } from './SpaceLoopsList'
import { spaceLoopsLogic } from './spaceLoopsLogic'
import { SpaceLoopTemplates } from './SpaceLoopTemplates'

/** A space's Loops tab: the loops, templates, then the loop builder, in the same layout as the Settings tab. */
export function SpaceLoops({ id }: { id: string }): JSX.Element {
    const { loops, loopsLoading, loopsUnavailable, activeCount } = useValues(spaceLoopsLogic({ id }))
    const { loadLoops, focusBuilder } = useActions(spaceLoopsLogic({ id }))

    return (
        <div className="-mx-4">
            <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-border px-6 py-2">
                <Text size="xs" variant="muted" className="min-w-0">
                    Loops run an agent task on a schedule or when an event happens, and post each run to this space.
                </Text>
                <Button size="sm" variant="primary" onClick={focusBuilder} data-attr="today-space-loop-new">
                    <IconPlus />
                    New loop
                </Button>
            </div>
            <div className="flex w-full max-w-200 flex-col gap-7 px-6 pt-6 pb-8">
                <SpaceSettingsSection
                    label="Loops"
                    action={
                        loops?.length ? (
                            <Text render={<span />} size="xs" variant="muted">
                                {`${activeCount} active`}
                            </Text>
                        ) : undefined
                    }
                >
                    {loopsLoading && !loops ? (
                        <div aria-hidden className="flex flex-col gap-px">
                            {[0, 1, 2].map((row) => (
                                <Skeleton key={row} className="h-12 w-full" />
                            ))}
                        </div>
                    ) : loopsUnavailable && !loops ? (
                        <Empty className="border border-dashed py-8">
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
                        <Empty className="border border-dashed py-8">
                            <EmptyHeader>
                                <EmptyMedia variant="icon">
                                    <IconRefresh />
                                </EmptyMedia>
                                <EmptyTitle>No loops in this space yet</EmptyTitle>
                                <EmptyDescription>
                                    Describe what to automate below, or start from a template. An agent sets up the loop
                                    with you, then it runs in the cloud on its own.
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    ) : (
                        <>
                            <SpaceLoopsFilterBar id={id} />
                            <SpaceLoopsList id={id} />
                        </>
                    )}
                </SpaceSettingsSection>
                <SpaceLoopTemplates id={id} />
                <SpaceLoopBuilderComposer id={id} />
            </div>
        </div>
    )
}
