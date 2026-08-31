import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

// Mirrors the backend skill-name rules (lowercase, numbers, single hyphens, no leading or
// trailing hyphen) so a retry is caught before it round-trips to the API.
const SKILL_NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const MAX_SKILL_NAME_LENGTH = 64

export function validateSkillName(value: string | undefined): string | undefined {
    const name = value?.trim()
    if (!name) {
        return 'Enter a name'
    }
    if (name.length > MAX_SKILL_NAME_LENGTH) {
        return `Use ${MAX_SKILL_NAME_LENGTH} characters or fewer`
    }
    if (!SKILL_NAME_PATTERN.test(name)) {
        return 'Use lowercase letters, numbers, and single hyphens'
    }
    return undefined
}

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
        errors: { new_name: validateSkillName },
        onSubmit: ({ new_name }) => onRename(new_name.trim()),
    })
}
