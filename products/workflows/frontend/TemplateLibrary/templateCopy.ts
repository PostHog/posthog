import posthog from 'posthog-js'

import { isCodeManagedTemplate } from './codeManagedTemplate'
import { omitNullDesign } from './omitNullDesign'
import { MessageTemplate } from './types'

export function templateCopy(template: MessageTemplate): Partial<MessageTemplate> {
    const email = template.content?.email
    return {
        name: `${template.name} (copy)`,
        description: template.description,
        content: email ? { ...template.content, email: omitNullDesign(email) } : template.content,
    }
}

export function captureTemplateDuplicated(original: MessageTemplate): void {
    posthog.capture('message template duplicated', {
        template_id: original.id,
        code_managed: isCodeManagedTemplate(original),
    })
}
