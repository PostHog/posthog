import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus, IconRefresh } from '@posthog/icons'
import { Button, Skeleton, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { TodayPaneRow } from '~/layout/today/TodayPaneRow'

import { NEW_LOOP_ID } from './loopForm'
import { loopsLogic } from './loopsLogic'

export function LoopsSidebarSection(): JSX.Element {
    const { loops, loopsFailed, atLoopLimit } = useValues(loopsLogic)
    const { loadLoopsPage } = useActions(loopsLogic)
    const { location } = useValues(router)
    const currentPath = removeProjectIdIfPresent(location.pathname)
    const newLoopDisabledReason = atLoopLimit ? 'This project has the maximum number of loops' : null

    return (
        <TooltipProvider>
            <section aria-label="Loops" data-attr="today-section-loops">
                <div className="TodayPane__heading flex items-center justify-between gap-2">
                    <span className="Today__label">Loops</span>
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <Button
                                    size="icon-xs"
                                    className="text-muted-foreground"
                                    aria-label="New loop"
                                    disabled={!!newLoopDisabledReason}
                                    render={<LinkPrimitive to={urls.taskLoop(NEW_LOOP_ID)} />}
                                    data-attr="today-new-loop"
                                />
                            }
                        >
                            <IconPlus />
                        </TooltipTrigger>
                        <TooltipContent>{newLoopDisabledReason ?? 'New loop'}</TooltipContent>
                    </Tooltip>
                </div>
                {loops === null ? (
                    loopsFailed ? (
                        <div className="TodayPane__state" role="alert">
                            Loops didn’t load.
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => loadLoopsPage()}
                                data-attr="today-loops-retry"
                            >
                                Try again
                            </Button>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-1 px-2" aria-busy="true" aria-label="Loading loops">
                            <Skeleton className="h-6" />
                            <Skeleton className="h-6" />
                        </div>
                    )
                ) : loops.length === 0 ? (
                    <div className="TodayPane__state">
                        A loop starts an agent task on a schedule, from an API call, or when you run it.
                        <Button
                            variant="outline"
                            size="sm"
                            render={<LinkPrimitive to={urls.taskLoop(NEW_LOOP_ID)} />}
                            data-attr="today-loops-empty-new-loop"
                        >
                            <IconPlus />
                            New loop
                        </Button>
                    </div>
                ) : (
                    <div className="flex flex-col gap-px">
                        {loops.map((loop) => (
                            <TodayPaneRow
                                key={loop.id}
                                label={loop.name}
                                meta={
                                    !loop.enabled ? 'Paused' : loop.last_run_status === 'failed' ? 'Failed' : undefined
                                }
                                icon={<IconRefresh />}
                                to={urls.taskLoop(loop.id)}
                                active={currentPath === urls.taskLoop(loop.id)}
                                dataAttr="today-loop"
                            />
                        ))}
                    </div>
                )}
            </section>
        </TooltipProvider>
    )
}
