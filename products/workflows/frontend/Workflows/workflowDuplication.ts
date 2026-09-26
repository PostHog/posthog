type ServerOwnedField = 'id' | 'team_id' | 'created_at' | 'updated_at' | 'origin_product'

/** Works on the hand-written `HogFlow` and on the generated `HogFlowApi` alike. */
export function prepareWorkflowDuplicate<T extends { name?: string | null; status?: unknown }>(
    workflow: T
): Omit<T, ServerOwnedField | 'name' | 'status'> & { name: string; status: 'draft' } {
    const duplicate: Record<string, unknown> = {
        ...workflow,
        name: `${workflow.name} (copy)`,
        status: 'draft',
    }

    delete duplicate.id
    delete duplicate.team_id
    delete duplicate.created_at
    delete duplicate.updated_at
    delete duplicate.origin_product

    return duplicate as Omit<T, ServerOwnedField | 'name' | 'status'> & { name: string; status: 'draft' }
}
