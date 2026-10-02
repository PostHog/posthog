import api from 'lib/api'
import type { AiFirstHandoffLogicProps } from 'scenes/max/aiFirstCreate/aiFirstHandoffLogic'
import { urls } from 'scenes/urls'

// pinned: MCP tool name from products/workflows/mcp/email_templates.yaml
const CREATE_TEMPLATE_TOOL = 'workflows-create-email-template'

/**
 * Fallback for a completed create whose output carries no record: the template is found by exact name,
 * newest `created_at` first. The list endpoint has no search param; it returns the newest templates first,
 * so the first page holds the one just made. No name means no guess.
 */
export async function findCreatedTemplateId(name: unknown): Promise<string | null> {
    const search = typeof name === 'string' && name.trim() ? name.trim() : undefined
    if (!search) {
        return null
    }
    const { results } = await api.messaging.getTemplates()
    const match = results
        .filter((template) => template.name === search)
        .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))[0]
    return match?.id ?? null
}

/** A completed `workflows-create-email-template` opens the panel and routes to the saved template. */
export const NEW_TEMPLATE_HANDOFF: AiFirstHandoffLogicProps = {
    toolName: CREATE_TEMPLATE_TOOL,
    findCreatedId: (innerInput) => findCreatedTemplateId(innerInput?.name),
    urlFor: (id) => urls.workflowsLibraryTemplate(id),
    notOpenedMessage: 'Your email template was created, but it could not be opened. Find it in the library.',
    // pinned: analytics event names
    eventPrefix: 'email template ai composer',
    createdEvent: 'email template ai composer created template',
    createdIdProperty: 'template_id',
}
