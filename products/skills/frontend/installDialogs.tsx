import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { validateSkillName } from './skillConstants'

// Recovery path for a name collision on install: let the user pick a different name and retry.
export function openInstallRenameDialog({
    attemptedName,
    onRename,
}: {
    attemptedName: string
    onRename: (newName: string) => void
}): void {
    LemonDialog.openForm({
        title: 'Choose a different name',
        description: `A skill named "${attemptedName}" is already in your project. Pick a new name to install another copy.`,
        initialValues: { new_name: attemptedName },
        content: (
            <LemonField name="new_name" label="Skill name">
                <LemonInput autoFocus data-attr="community-skill-install-rename" placeholder="my-skill-name" />
            </LemonField>
        ),
        errors: { new_name: (name) => validateSkillName((name ?? '').trim()) },
        onSubmit: ({ new_name }) => onRename(new_name.trim()),
    })
}
