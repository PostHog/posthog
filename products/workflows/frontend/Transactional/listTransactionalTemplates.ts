import { listAllPages } from 'scenes/settings/environment/cloudEnvironmentsLogic'

import { messagingTemplatesList } from 'products/messaging/frontend/generated/api'
import type { MessageTemplateApi } from 'products/messaging/frontend/generated/api.schemas'

export async function listTransactionalTemplates(
    projectId: string
): Promise<(MessageTemplateApi & { transactional_hog_flow_id: string })[]> {
    const templates = await listAllPages((params) =>
        messagingTemplatesList(projectId, { ...params, basic: true, transactional: true })
    )
    return templates.flatMap(({ transactional_hog_flow_id, ...template }) =>
        transactional_hog_flow_id ? [{ ...template, transactional_hog_flow_id }] : []
    )
}
