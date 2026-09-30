import type { HogFunctionTemplateType } from '~/types'

/** Destination templates that send a message and are therefore created as workflows. */
export const MESSAGING_DESTINATION_TEMPLATE_IDS: ReadonlySet<string> = new Set([
    'template-slack',
    'template-discord',
    'template-microsoft-teams',
    'template-whatsapp',
    'template-mailgun-send-email',
    'template-kudosity-sms',
])

/**
 * Sub-templates are the internal alert flows (surveys, error tracking, logs alerts) that reuse the
 * Slack, Discord and Teams templates. Those keep creating hog functions, so they never match here.
 */
export function isMessagingDestinationTemplate(
    template: Pick<HogFunctionTemplateType, 'id' | 'type'> & { sub_template_id?: string | null }
): boolean {
    return (
        template.type === 'destination' &&
        !template.sub_template_id &&
        MESSAGING_DESTINATION_TEMPLATE_IDS.has(template.id)
    )
}
