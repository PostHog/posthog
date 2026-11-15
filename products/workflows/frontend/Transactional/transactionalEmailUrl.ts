import { urls } from 'scenes/urls'

export function transactionalEmailUrl({
    codeEmailId,
    templateId,
}: {
    codeEmailId: string | null
    templateId: string | null
}): string | null {
    if (codeEmailId) {
        return urls.transactionalCodeEmail(codeEmailId)
    }
    if (templateId) {
        return urls.transactionalTemplate(templateId)
    }
    return null
}
