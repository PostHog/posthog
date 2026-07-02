import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    MenuLabel,
} from '@posthog/quill-primitives'

import { tasksLogic } from '../../../logics/tasksLogic'
import { TaskAssigneeFilter } from '../../../types/taskTypes'

export function TaskAssigneeFilterMenu(): JSX.Element {
    const { assigneeFilter } = useValues(tasksLogic)
    const { setAssigneeFilter } = useActions(tasksLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button type="button" size="icon-lg" aria-label="Filter tasks">
                        <IconFilter />
                    </Button>
                }
            />
            <DropdownMenuContent align="start" side="bottom" sideOffset={6} className="min-w-fit">
                <MenuLabel>Show</MenuLabel>
                <DropdownMenuRadioGroup
                    value={assigneeFilter}
                    onValueChange={(value) => setAssigneeFilter(value as TaskAssigneeFilter)}
                >
                    <DropdownMenuRadioItem value="for_you">For you</DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="team_scouts">Team scouts</DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
