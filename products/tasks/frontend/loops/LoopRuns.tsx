import { useActions, useValues } from 'kea'

import {
    Badge,
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SettingsSection } from '../components/SettingsSection'
import type { LoopRunDTOApi } from '../generated/api.schemas'
import { loopSceneLogic } from './loopSceneLogic'

const RUN_STATUS: Record<string, { label: string; variant: 'default' | 'info' | 'destructive' | 'success' }> = {
    not_started: { label: 'Not started', variant: 'default' },
    queued: { label: 'Queued', variant: 'info' },
    in_progress: { label: 'Running', variant: 'info' },
    completed: { label: 'Completed', variant: 'success' },
    failed: { label: 'Failed', variant: 'destructive' },
    cancelled: { label: 'Canceled', variant: 'default' },
}

function LoopRunRow({ run }: { run: LoopRunDTOApi }): JSX.Element {
    const status = RUN_STATUS[run.status] ?? { label: run.status, variant: 'default' as const }
    return (
        <Item
            variant="outline"
            size="sm"
            // The global link color would otherwise tint the whole row.
            className="text-foreground"
            render={<LinkPrimitive to={urls.aiTask(run.task_id)} />}
            data-attr="loop-run-row"
        >
            <ItemContent className="min-w-0">
                <ItemTitle>
                    <span translate="no">{dayjs(run.created_at).format('MMM D, HH:mm')}</span>
                </ItemTitle>
                {(run.error_message || run.branch) && (
                    <ItemDescription className="truncate">{run.error_message || run.branch}</ItemDescription>
                )}
            </ItemContent>
            <ItemActions>
                <Badge variant={status.variant}>{status.label}</Badge>
            </ItemActions>
        </Item>
    )
}

export function LoopRuns({ id }: { id: string }): JSX.Element {
    const { runs, runsLoading } = useValues(loopSceneLogic({ id }))
    const { loadRuns } = useActions(loopSceneLogic({ id }))

    return (
        <SettingsSection
            label="Recent runs"
            description="Each run starts a task. Open a run to see what the agent did."
            action={
                <Button
                    variant="outline"
                    size="sm"
                    loading={runsLoading}
                    onClick={() => loadRuns()}
                    data-attr="loop-runs-refresh"
                >
                    Refresh
                </Button>
            }
        >
            {runs === null ? (
                runsLoading ? (
                    <div className="flex flex-col gap-1" aria-busy="true">
                        <Skeleton className="h-12 w-full" />
                        <Skeleton className="h-12 w-full" />
                    </div>
                ) : (
                    <Text size="xs" variant="muted" role="alert">
                        The runs didn’t load. Select refresh to try again.
                    </Text>
                )
            ) : runs.length === 0 ? (
                <Empty className="py-6">
                    <EmptyHeader>
                        <EmptyTitle>No runs yet</EmptyTitle>
                        <EmptyDescription>
                            Runs show up here when a trigger fires or you select Run now.
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : (
                <ItemGroup combined>
                    {runs.map((run) => (
                        <LoopRunRow key={run.id} run={run} />
                    ))}
                </ItemGroup>
            )}
        </SettingsSection>
    )
}
