import { useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill-primitives'

import { DROPDOWN_PARTS, SHEET_PARTS, TodayMenuParts } from '~/layout/today/todayMenuParts'
import { panelChatTaskFor } from '~/layout/today/todayPanelChat'
import { TodayPanelMoveMenuItems } from '~/layout/today/TodayPanelMoveMenuItems'
import { TodaySheetMenu } from '~/layout/today/TodaySheetMenu'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import type { TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import type { Task } from '../../../types/taskTypes'
import { TaskMenuItems } from './TaskMenuItems'

export interface QuillTaskMenuProps {
    task: Task
    selectedRun: TaskRunDetailDTOApi | null
    onArchive: () => void
}

export function QuillTaskMenu({ task, selectedRun, onArchive }: QuillTaskMenuProps): JSX.Element {
    const { todayRailEnabled, phoneLayout } = useValues(todayShellLogic)
    const [sheetOpen, setSheetOpen] = useState(false)
    // The phone layout has no floating or docked panel to move the chat into.
    const chat = todayRailEnabled && !phoneLayout ? panelChatTaskFor(task, selectedRun) : null

    const items = (parts: TodayMenuParts): JSX.Element => (
        <TaskMenuItems
            parts={parts}
            task={task}
            run={selectedRun}
            onArchive={onArchive}
            placement={chat && <TodayPanelMoveMenuItems parts={parts} chat={chat} dataAttrPrefix="task" />}
        />
    )

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
                    {items(SHEET_PARTS)}
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
                {items(DROPDOWN_PARTS)}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
