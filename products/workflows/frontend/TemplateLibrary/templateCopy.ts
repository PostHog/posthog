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
