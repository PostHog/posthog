import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

// Any Liquid output `{{ … }}` or tag `{% … %}`. Variables can sit anywhere inside one, such as
// `{% if variables.show_receipt %}` or `{{ variables.name | default: variables.fallback_name }}`.
const LIQUID_EXPRESSION = /\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\}/g
const VARIABLE_REFERENCE = /\bvariables\.([A-Za-z_][A-Za-z0-9_]*)/g

/** The `message_data` keys an email reads, in the order they first appear in its sender, subject, preheader and body. */
export function variablesInEmail(
    email: Pick<EmailTemplate, 'subject' | 'html' | 'text' | 'preheader' | 'from' | 'replyTo'>
): string[] {
    const from = typeof email.from === 'object' && email.from ? email.from : {}
    const source = [from.name, from.email, email.replyTo, email.subject, email.preheader, email.html, email.text]
        .filter(Boolean)
        .join('\n')
    const expressions = source.match(LIQUID_EXPRESSION) ?? []
    return [
        ...new Set(
            expressions.flatMap((expression) => [...expression.matchAll(VARIABLE_REFERENCE)].map((match) => match[1]))
        ),
    ]
}

/** Editor globals for a transactional email: its variables feed the merge tags and Liquid autocomplete. */
export function transactionalEditorGlobals(names: string[]): { variables: Record<string, string> } {
    return { variables: Object.fromEntries(names.map((name) => [name, ''])) }
}

/** A name a person typed, made safe to use after `variables.`. */
export function cleanVariableName(name: string): string {
    return name
        .trim()
        .replace(/[^A-Za-z0-9_]/g, '_')
        .replace(/^(\d)/, '_$1')
}
