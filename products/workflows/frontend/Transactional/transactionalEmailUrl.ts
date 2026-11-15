import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { SEND_FILTER_PARAMS } from './log/transactionalEmailLogLogic'

// A send and a metrics row both name the email behind them with these two fields.
interface EmailPage {
    code_email_id: string | null
    template_id: string | null
}

interface StatsRow {
    key: string
    label: string
    code_email_id?: string | null
    template_id?: string | null
}

export function transactionalEmailUrl(email: EmailPage | null | undefined): string | null {
    if (email?.code_email_id) {
        return urls.transactionalCodeEmail(email.code_email_id)
    }
    if (email?.template_id) {
        return urls.transactionalTemplate(email.template_id)
    }
    return null
}

export function transactionalEmailSendsUrl(
    email: EmailPage | null | undefined,
    searchParams: Record<string, unknown>
): string | null {
    const url = transactionalEmailUrl(email)
    if (!url) {
        return null
    }
    const filters = Object.fromEntries(
        SEND_FILTER_PARAMS.filter((param) => searchParams[param] != null).map((param) => [param, searchParams[param]])
    )
    return combineUrl(url, { tab: 'sends', ...filters }).url
}

export function transactionalEmailStatsRowUrl(row: StatsRow): string | null {
    // During a deploy, a Django pod without `template_id` can still answer. It keys a template's row by the template's
    // id and leaves the label empty for any other row.
    if (row.template_id === undefined) {
        return row.label ? urls.transactionalTemplate(row.key) : null
    }
    return transactionalEmailUrl({ code_email_id: row.code_email_id ?? null, template_id: row.template_id })
}
