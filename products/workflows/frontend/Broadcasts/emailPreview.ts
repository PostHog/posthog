import { LiquidRenderer } from 'lib/utils/liquid'

const OUTPUT_REGEX = /\{\{(.*?)\}\}/g

/** The person values a preview renders against, shaped like the worker's `person` global. */
export interface EmailPreviewPerson {
    id: string
    properties: Record<string, any>
}

/**
 * Wrap every output tag that this person has no value for in `{% raw %}`, so it survives the render
 * as its own source text instead of collapsing to the empty string the real send would produce.
 * A reader can then see which variables are missing rather than reading a blank space.
 *
 * Expressions carrying a filter are left alone: the filter may supply the fallback (`| default:`),
 * so an undefined value there is not necessarily a gap. A variable that only exists inside a
 * `{% for %}` body is out of scope at this point and is marked, which reads as a false gap; email
 * built in the editor uses merge tags rather than loops, so accept that over walking the AST.
 */
function markUnresolved(template: string, context: Record<string, any>): string {
    return template.replace(OUTPUT_REGEX, (match, inner) => {
        const expression = String(inner).trim()
        if (!expression || expression.includes('|')) {
            return match
        }
        return LiquidRenderer.resolves(expression, context) ? match : `{% raw %}${match}{% endraw %}`
    })
}

/**
 * Render one templated email field against a person, the way the send will.
 *
 * Returns the template unchanged when it can't be parsed, because a preview must never be the
 * thing that breaks the review step.
 */
export function renderEmailPreview(template: string, person: EmailPreviewPerson | null): string {
    if (!template || !person) {
        return template
    }
    const context = {
        person: {
            id: person.id,
            properties: person.properties,
        },
        // Injected by the email service per recipient. Stand it in so a preview doesn't report the
        // unsubscribe link every marketing email carries as a missing variable.
        unsubscribe_url: '#unsubscribe',
        now: new Date(),
    }
    try {
        return LiquidRenderer.render(markUnresolved(template, context), context)
    } catch {
        return template
    }
}
