import type { Context } from '@/tools/types'

export const isShortId = (id: string): boolean => {
    return /^[A-Za-z0-9]{8}$/.test(id)
}

export const resolveInsightId = async (
    context: Context,
    insightId: string,
    projectId: string
): Promise<number> => {
    if (isShortId(insightId)) {
        const result = await context.api.insights({ projectId }).get({ insightId })

        if (!result.success) {
            throw new Error(`Failed to resolve insight: ${result.error.message}`)
        }

        return result.data.id
    }

    const numericId = Number.parseInt(insightId, 10)
    if (Number.isNaN(numericId)) {
        throw new Error(`Invalid insight ID format: ${insightId}`)
    }

    return numericId
}
