import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { SEND_FILTER_PARAMS } from './log/transactionalEmailLogLogic'

interface EmailPage {
    codeEmailId: string | null
    templateId: string | null
}

export function transactionalEmailUrl({ codeEmailId, templateId }: EmailPage): string | null {
    if (codeEmailId) {
        return urls.transactionalCodeEmail(codeEmailId)
    }
    if (templateId) {
        return urls.transactionalTemplate(templateId)
    }
    return null
}

export function transactionalEmailSendsUrl(email: EmailPage, searchParams: Record<string, unknown>): string | null {
    const url = transactionalEmailUrl(email)
    if (!url) {
        return null
    }
    const filters = Object.fromEntries(
        SEND_FILTER_PARAMS.filter((param) => searchParams[param] != null).map((param) => [param, searchParams[param]])
    )
    return combineUrl(url, { tab: 'sends', ...filters }).url
}
