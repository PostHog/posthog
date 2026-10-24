import { MessageTemplate } from './types'

export function templateCopy(template: MessageTemplate): Partial<MessageTemplate> {
    return {
        name: `${template.name} (copy)`,
        description: template.description,
        content: template.content,
    }
}
