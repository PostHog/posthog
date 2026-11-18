import { LemonInput } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { nextTaskTitle } from '../../lib/task-title'

/** Matches `Task.title` on the server, which rejects anything longer. */
const TASK_TITLE_MAX_LENGTH = 255

export function openRenameTaskDialog(currentTitle: string, onRename: (title: string) => void): void {
    LemonDialog.openForm({
        title: 'Rename task',
        initialValues: { title: currentTitle },
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
        onSubmit: ({ title }) => {
            const renamed = nextTaskTitle(title, currentTitle)
            if (renamed) {
                onRename(renamed)
            }
        },
    })
}
