import { ApiError } from 'lib/api'

import { transactionalCodeEmailsList } from 'products/messaging/frontend/generated/api'
import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

export async function listCodeEmails(projectId: string): Promise<CodeEmailApi[]> {
    try {
        return await transactionalCodeEmailsList(projectId)
    } catch (error) {
        // The endpoint answers 404 while the project can't send email from code yet.
        if (error instanceof ApiError && error.status === 404) {
            return []
        }
        throw error
    }
}
