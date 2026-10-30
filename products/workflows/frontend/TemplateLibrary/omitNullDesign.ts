import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

/** The template API rejects a null design, which applying a text-only template leaves in the email. */
export function omitNullDesign(email: EmailTemplate): EmailTemplate {
    if (email.design != null) {
        return email
    }
    const { design: _design, ...emailWithoutDesign } = email
    return emailWithoutDesign as EmailTemplate
}
