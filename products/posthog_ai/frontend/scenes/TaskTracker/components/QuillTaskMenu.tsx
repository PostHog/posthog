import { useActions, useValues } from 'kea'
import { type ReactNode, useState } from 'react'

import { IconArchive, IconBug, IconEllipsis, IconInfo } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    MenuLabel,
    cn,
} from '@posthog/quill-primitives'

import { dayjs } from 'lib/dayjs'

import { SHEET_PARTS } from '~/layout/today/todayMenuParts'
import { TodaySheetMenu } from '~/layout/today/TodaySheetMenu'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import type { TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { debugLogsLogic } from '../../../logics/debugLogsLogic'
import { modelCatalogueLogic } from '../../../logics/modelCatalogueLogic'
import type { Task } from '../../../types/taskTypes'
import { getTaskRunMetadataFields } from './taskRunMetadataFields'

export interface QuillTaskMenuProps {
    task: Task
    selectedRun: TaskRunDetailDTOApi | null
    onArchive: () => void
}

function RelativeTime({ time }: { time: string }): JSX.Element {
    return (
        <time dateTime={time} title={dayjs(time).format('MMM D, YYYY HH:mm:ss')}>
            {dayjs(time).fromNow()}
        </time>
    )
}

function FactList({
    facts,
    className = 'gap-1 px-2 pb-1 text-xs',
}: {
    facts: { label: string; value: ReactNode }[]
    className?: string
}): JSX.Element {
    return (
        <dl className={cn('m-0 flex flex-col', className)}>
            {facts.map((fact) => (
                <div key={fact.label} className="flex items-baseline justify-between gap-4">
                    <dt className="text-muted-foreground">{fact.label}</dt>
                    <dd className="m-0 min-w-0 truncate text-end text-foreground">{fact.value}</dd>
                </div>
            ))}
        </dl>
    )
}

export function QuillTaskMenu({ task, selectedRun, onArchive }: QuillTaskMenuProps): JSX.Element {
    const { catalogue } = useValues(modelCatalogueLogic)
    const { canControlDebugLogs, debugLogsEnabled } = useValues(debugLogsLogic)
    const { setDebugLogsEnabled } = useActions(debugLogsLogic)
    const { todayRailEnabled, phoneLayout } = useValues(todayShellLogic)
    const [sheetOpen, setSheetOpen] = useState(false)

    const taskFacts = [
        { label: 'Task ID', value: <span className="font-mono">{task.slug}</span> },
        ...(task.repository ? [{ label: 'Repository', value: task.repository }] : []),
        { label: 'Created by', value: task.created_by?.first_name || task.created_by?.email || 'Unknown' },
        { label: 'Created', value: <RelativeTime time={task.created_at} /> },
    ]
    const runFacts = selectedRun
        ? getTaskRunMetadataFields(selectedRun, catalogue).map((field) => ({
              label: field.label,
              value: field.kind === 'time' ? <RelativeTime time={field.value} /> : field.value,
          }))
        : []

    if (todayRailEnabled && phoneLayout) {
        return (
            <>
                <Button
                    variant="default"
                    size="icon-lg"
                    aria-label="Task actions"
                    onClick={() => setSheetOpen(true)}
                    data-attr="run-staff-menu"
                >
                    <IconEllipsis />
                </Button>
                <TodaySheetMenu open={sheetOpen} onOpenChange={setSheetOpen} title={task.title || 'Task'}>
                    <SHEET_PARTS.Sub
                        label={
                            <>
                                <IconInfo />
                                Task details
                            </>
                        }
                        title="Task details"
                        dataAttr="task-details"
                    >
                        <div className="flex flex-col gap-4 px-4 py-3">
                            <section className="flex flex-col gap-2">
                                <MenuLabel className="px-0">Task</MenuLabel>
                                <FactList facts={taskFacts} className="gap-2 text-sm" />
                            </section>
                            {runFacts.length > 0 && (
                                <section className="flex flex-col gap-2">
                                    <MenuLabel className="px-0">Run</MenuLabel>
                                    <FactList facts={runFacts} className="gap-2 text-sm" />
                                </section>
                            )}
                        </div>
                    </SHEET_PARTS.Sub>
                    {canControlDebugLogs && (
                        <SHEET_PARTS.Item
                            onClick={() => setDebugLogsEnabled(!debugLogsEnabled)}
                            dataAttr="run-toggle-debug-logs"
                        >
                            <IconBug />
                            {debugLogsEnabled ? 'Hide debug logs' : 'Show debug logs'}
                        </SHEET_PARTS.Item>
                    )}
                    <SHEET_PARTS.Separator />
                    <SHEET_PARTS.Item variant="destructive" onClick={onArchive} dataAttr="task-archive">
                        <IconArchive />
                        Archive task
                    </SHEET_PARTS.Item>
                </TodaySheetMenu>
            </>
        )
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button variant="default" size="icon" aria-label="Task details" data-attr="run-staff-menu">
                        <IconEllipsis />
                    </Button>
                }
            />
            <DropdownMenuContent align="end" className="min-w-64 max-w-80">
                <MenuLabel>Task</MenuLabel>
                <FactList facts={taskFacts} />
                {runFacts.length > 0 && (
                    <>
                        <DropdownMenuSeparator />
                        <MenuLabel>Run</MenuLabel>
                        <FactList facts={runFacts} />
                    </>
                )}
                <DropdownMenuSeparator />
                {canControlDebugLogs && (
                    <DropdownMenuCheckboxItem
                        checked={debugLogsEnabled}
                        onCheckedChange={setDebugLogsEnabled}
                        data-attr="run-toggle-debug-logs"
                    >
                        Show debug logs
                    </DropdownMenuCheckboxItem>
                )}
                <DropdownMenuItem variant="destructive" onClick={onArchive} data-attr="task-archive">
                    <IconArchive />
                    Archive task
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
