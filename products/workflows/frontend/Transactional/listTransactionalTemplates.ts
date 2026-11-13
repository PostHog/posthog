import { listAllPages } from 'scenes/settings/environment/cloudEnvironmentsLogic'

import { messagingTemplatesList } from 'products/messaging/frontend/generated/api'
import type { MessageTemplateApi } from 'products/messaging/frontend/generated/api.schemas'

const listBasicTemplates = (projectId: string, filterToTransactional: boolean): Promise<MessageTemplateApi[]> =>
    listAllPages((params) =>
        messagingTemplatesList(projectId, {
            ...params,
            basic: true,
            ...(filterToTransactional ? { transactional: true } : {}),
        })
    )

const answeredByServerWithoutTransactionalFilter = (template: MessageTemplateApi): boolean => !('has_draft' in template)

export async function listTransactionalTemplates(
    projectId: string
): Promise<(MessageTemplateApi & { transactional_hog_flow_id: string })[]> {
    const filtered = await listBasicTemplates(projectId, true)
    const templates = filtered.some(answeredByServerWithoutTransactionalFilter)
        ? await listBasicTemplates(projectId, false)
        : filtered
    return templates.flatMap(({ transactional_hog_flow_id, ...template }) =>
        transactional_hog_flow_id
            ? [
                  {
                      ...template,
                      transactional_hog_flow_id,
                      has_draft: template.has_draft ?? template.draft_content != null,
                  },
              ]
            : []
    )
}
