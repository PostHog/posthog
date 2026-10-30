import { LiquidRenderer } from 'lib/utils/liquid'

// The email editor saves a link's spaces as %20, including the spaces inside a {{ }} tag.
const ENCODED_SPACE_IN_TAG = /\{[{%][^}]*%20/

export function getTemplatingError(value: string, templating?: string): string | undefined {
    if (templating === 'liquid' && typeof value === 'string') {
        try {
            LiquidRenderer.parse(value)
        } catch (e: any) {
            if (ENCODED_SPACE_IN_TAG.test(value)) {
                return 'A link has a variable with spaces inside {{ }}, which the email editor saves as %20. Remove the spaces, for example {{person.properties.name}}.'
            }
            return `Liquid template error: ${e.message}`
        }
    }
}
