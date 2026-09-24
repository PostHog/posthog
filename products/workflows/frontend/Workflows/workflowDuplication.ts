import type { HogFlow } from './hogflows/types'

export function prepareWorkflowDuplicate(workflow: HogFlow): Partial<HogFlow> {
    const duplicate: Partial<HogFlow> & { origin_product?: unknown } = {
        ...workflow,
        name: `${workflow.name} (copy)`,
        status: 'draft',
    }

    delete duplicate.id
    delete duplicate.key
    delete duplicate.team_id
    delete duplicate.created_at
    delete duplicate.updated_at
    delete duplicate.origin_product
    delete duplicate.managed_by
    delete duplicate.created_via
    delete duplicate.source_repository
    delete duplicate.source_path
    delete duplicate.source_ref

    return duplicate
}
