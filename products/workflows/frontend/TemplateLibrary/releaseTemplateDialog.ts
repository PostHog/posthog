import { LemonDialog } from '@posthog/lemon-ui'

import { MessageTemplate } from './types'

export function openReleaseTemplateDialog(template: MessageTemplate, onRelease: () => void): void {
    const nextUpload = template.source_path ? `The next upload of ${template.source_path}` : 'The next upload from code'
    LemonDialog.open({
        title: 'Stop managing this template in code?',
        description: `You can edit this template here again. ${nextUpload} makes it managed by code again and replaces changes made here.`,
        primaryButton: {
            children: 'Stop managing in code',
            'data-attr': 'message-template-release-confirm',
            onClick: onRelease,
        },
        secondaryButton: { children: 'Cancel' },
    })
}
