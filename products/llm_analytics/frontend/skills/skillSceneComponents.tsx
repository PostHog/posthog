import { LemonDialog } from '~/lib/lemon-ui/LemonDialog'

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
