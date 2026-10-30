import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { MenuLabel, Separator, cn } from '@posthog/quill-primitives'

import { dayjs } from 'lib/dayjs'

import type { TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { modelCatalogueLogic } from '../../../logics/modelCatalogueLogic'
import type { Task } from '../../../types/taskTypes'
import { getTaskRunMetadataFields } from './taskRunMetadataFields'

export interface TaskMenuFactsProps {
    task: Task
    run: TaskRunDetailDTOApi | null
}

interface Fact {
    label: string
    value: ReactNode
}

function RelativeTime({ time }: { time: string }): JSX.Element {
    return (
        <time dateTime={time} title={dayjs(time).format('MMM D, YYYY HH:mm:ss')}>
            {dayjs(time).fromNow()}
        </time>
    )
}

function FactList({ facts, className }: { facts: Fact[]; className: string }): JSX.Element {
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

export function TaskMenuFacts({ task, run }: TaskMenuFactsProps): JSX.Element {
    const { catalogue } = useValues(modelCatalogueLogic)

    const taskFacts: Fact[] = [
        { label: 'Task ID', value: <span className="font-mono">{task.slug}</span> },
        ...(task.repository ? [{ label: 'Repository', value: task.repository }] : []),
        { label: 'Created by', value: task.created_by?.first_name || task.created_by?.email || 'Unknown' },
        { label: 'Created', value: <RelativeTime time={task.created_at} /> },
    ]
    const runFacts: Fact[] = run
        ? getTaskRunMetadataFields(run, catalogue).map((field) => ({
              label: field.label,
              value: field.kind === 'time' ? <RelativeTime time={field.value} /> : field.value,
          }))
        : []

    return (
        <>
            <MenuLabel>Task</MenuLabel>
            <FactList facts={taskFacts} className="gap-1 px-2 pb-1 text-xs" />
            {runFacts.length > 0 && (
                <>
                    {/* A plain separator, so the details render the same inside a menu and on a sheet page. */}
                    <Separator className="my-1" />
                    <MenuLabel>Run</MenuLabel>
                    <FactList facts={runFacts} className="gap-1 px-2 pb-1 text-xs" />
                </>
            )}
        </>
    )
}
