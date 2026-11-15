import { urls } from 'scenes/urls'

// A send and a metrics row both name the email behind them with these two fields.
interface EmailPage {
    code_email_id: string | null
    template_id: string | null
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
