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

export function openSkillVisibilityDialog(isGlobal: boolean, onConfirm: () => void): void {
    LemonDialog.open(
        isGlobal
            ? {
                  title: 'Make this skill visible to everyone?',
                  description:
                      'Every PostHog customer will be able to see and use this skill in their own projects. ' +
                      'Only PostHog staff can do this.',
                  primaryButton: { children: 'Make visible to everyone', onClick: onConfirm },
                  secondaryButton: { children: 'Cancel' },
              }
            : {
                  title: 'Make this skill private?',
                  description: "It will stop appearing in other customers' projects and go back to this project only.",
                  primaryButton: { children: 'Make private', onClick: onConfirm },
                  secondaryButton: { children: 'Cancel' },
              }
    )
}
