import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconComment } from '@posthog/icons'
import { Button, Label, Switch, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { taskRunArtifactsLogic } from '../taskRunArtifactsLogic'
import { ArtifactCommentThreadList } from './ArtifactCommentsMenu'

export function ArtifactCommentsButton({ logicProps }: { logicProps: TaskArtifactCommentsLogicProps }): JSX.Element {
    const { openCount } = useValues(taskArtifactCommentsLogic(logicProps))
    const { setCommentsOpen } = useActions(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    return (
        <Button
            size="lg"
            aria-label={openCount > 0 ? `Comments, ${openCount} open` : 'Comments'}
            onClick={() => setCommentsOpen(true)}
            data-attr="task-artifact-comments-toggle"
        >
            <IconComment />
            {openCount > 0 && (
                <Text size="xs" render={<span />} className="tabular-nums">
                    {openCount}
                </Text>
            )}
        </Button>
    )
}

export function ArtifactCommentsPage({
    logicProps,
    artifactName,
}: {
    logicProps: TaskArtifactCommentsLogicProps
    artifactName: string
}): JSX.Element {
    const { resolvedCount, showResolved } = useValues(taskArtifactCommentsLogic(logicProps))
    const { setShowResolved } = useActions(taskArtifactCommentsLogic(logicProps))
    const { setCommentsOpen } = useActions(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    const switchId = `task-artifact-comments-page-show-resolved-${logicProps.artifactId}`
    return (
        <section aria-label="Comments" className="flex min-h-0 flex-1 flex-col" data-attr="task-artifact-comments-page">
            <div className="flex h-12 shrink-0 items-center gap-1 border-b border-border bg-background px-1">
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon-lg"
                                aria-label={`Back to ${artifactName}`}
                                onClick={() => setCommentsOpen(false)}
                                data-attr="task-artifact-comments-back"
                            />
                        }
                    >
                        <IconChevronLeft />
                    </TooltipTrigger>
                    <TooltipContent>{`Back to ${artifactName}`}</TooltipContent>
                </Tooltip>
                <span className="flex min-w-0 flex-1 flex-col pl-1">
                    <Text size="sm" weight="medium" render={<span />}>
                        Comments
                    </Text>
                    <Text size="xs" variant="muted" render={<span />} className="truncate">
                        {artifactName}
                    </Text>
                </span>
                {resolvedCount > 0 && (
                    <div className="flex shrink-0 items-center gap-2 pr-2">
                        <Switch
                            id={switchId}
                            checked={showResolved}
                            onCheckedChange={(checked: boolean) => setShowResolved(checked)}
                            data-attr="task-artifact-comments-show-resolved"
                        />
                        <Label htmlFor={switchId}>{`Resolved (${resolvedCount})`}</Label>
                    </div>
                )}
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2">
                <ArtifactCommentThreadList logicProps={logicProps} cardsOnly />
            </div>
        </section>
    )
}
