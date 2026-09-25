import { IconEllipsis, IconPencil } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'

/** Matches `Task.title` on the server, which rejects anything longer. */
const TASK_TITLE_MAX_LENGTH = 255

export interface TaskActionsMenuProps {
    title: string
    onRename: (title: string) => void
}

/** Overflow menu for the task itself, beside the run actions in the title bar. */
export function TaskActionsMenu({ title, onRename }: TaskActionsMenuProps): JSX.Element {
    const openRenameDialog = (): void => {
        LemonDialog.openForm({
            title: 'Rename task',
            initialValues: { title },
            primaryButtonProps: { children: 'Rename' },
            showErrorsOnTouch: true,
            content: (
                <LemonField name="title">
                    <LemonInput placeholder="Task name" maxLength={TASK_TITLE_MAX_LENGTH} autoFocus />
                </LemonField>
            ),
            errors: {
                title: (value) => (!value?.trim() ? 'Enter a name for the task' : undefined),
            },
            onSubmit: ({ title: newTitle }) => {
                onRename(newTitle.trim())
            },
        })
    }

    return (
        <LemonMenu
            items={[
                {
                    label: 'Rename',
                    icon: <IconPencil />,
                    onClick: openRenameDialog,
                    'data-attr': 'task-rename',
                },
            ]}
        >
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconEllipsis />}
                tooltip="Task options"
                data-attr="task-actions-menu"
            />
        </LemonMenu>
    )
}
