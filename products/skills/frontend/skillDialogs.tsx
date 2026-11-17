import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { LemonDialog } from '~/lib/lemon-ui/LemonDialog'

import { SKILL_NAME_MAX_LENGTH, validateSkillName } from './skillConstants'

export function openArchiveSkillDialog(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Archive skill?',
        description: 'All versions of this skill will be archived. This action cannot be undone.',
        primaryButton: { children: 'Archive', status: 'danger', onClick: onConfirm },
        secondaryButton: { children: 'Cancel' },
    })
}

/** Collect the new name, then hand it to `onRename`. */
export function openRenameSkillDialog(skillName: string, onRename: (newName: string) => void): void {
    LemonDialog.openForm({
        title: 'Rename skill',
        description:
            "Agents call the skill by its name, and the name is also its URL and its folder in the zip export. Renaming keeps the skill's version history and owners.",
        initialValues: { newName: skillName },
        content: (
            <LemonField name="newName" label="New skill name">
                <LemonInput
                    data-attr="llma-skill-rename-name"
                    placeholder="my-skill-name"
                    maxLength={SKILL_NAME_MAX_LENGTH}
                    autoFocus
                />
            </LemonField>
        ),
        errors: {
            newName: (name: string) => validateSkillName(name),
        },
        onSubmit: ({ newName }) => onRename(newName),
    })
}
