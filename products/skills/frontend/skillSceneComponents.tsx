import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { LemonDialog } from '~/lib/lemon-ui/LemonDialog'

import { SKILL_NAME_MAX_LENGTH, validateSkillName } from './skillConstants'

export { LLMSkillsScene } from './LLMSkillsScene'
export { LLMSkillScene } from './LLMSkillScene'

export function openArchiveSkillDialog(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Archive skill?',
        description: 'All versions of this skill will be archived. This action cannot be undone.',
        primaryButton: { children: 'Archive', status: 'danger', onClick: onConfirm },
        secondaryButton: { children: 'Cancel' },
    })
}

export function openRenameSkillDialog(
    currentName: string,
    onRename: (currentName: string, newName: string) => void
): void {
    LemonDialog.openForm({
        title: 'Rename skill',
        description: 'Renaming applies to every version of this skill.',
        initialValues: { newName: currentName },
        content: (
            <LemonField name="newName" label="New skill name">
                <LemonInput
                    data-attr="llma-skill-rename-name"
                    placeholder="my-skill"
                    maxLength={SKILL_NAME_MAX_LENGTH}
                    autoFocus
                />
            </LemonField>
        ),
        errors: {
            newName: (name: string) =>
                name === currentName ? 'Enter a name different from the current one' : validateSkillName(name),
        },
        onSubmit: ({ newName }) => onRename(currentName, newName),
    })
}
