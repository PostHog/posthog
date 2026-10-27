import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

// Matches the name in a Liquid placeholder such as `{{ variables.reset_link }}` or `{{ variables.name | default: "there" }}`.
const VARIABLE_PATTERN = /\{\{-?\s*variables\.([A-Za-z_][A-Za-z0-9_]*)/g

/** The `message_data` keys an email reads, in the order they first appear in the subject, preheader and body. */
export function variablesInEmail(email: Pick<EmailTemplate, 'subject' | 'html' | 'text' | 'preheader'>): string[] {
    const source = [email.subject, email.preheader, email.html, email.text].filter(Boolean).join('\n')
    return [...new Set([...source.matchAll(VARIABLE_PATTERN)].map((match) => match[1]))]
}

export function variablePlaceholder(name: string): string {
    return `{{ variables.${name} }}`
}
