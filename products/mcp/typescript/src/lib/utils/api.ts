import { ApiListResponseSchema } from '@/schema/api'

import type { z } from 'zod'

export const withPagination = async <T>(
    url: string,
    apiToken: string,
    dataSchema: z.ZodType<T>
): Promise<T[]> => {
    const response = await fetch(url, {
        headers: {
            Authorization: `Bearer ${apiToken}`,
        },
    })

    if (!response.ok) {
        throw new Error(`Failed to fetch ${url}: ${response.statusText}`)
    }

    const data = await response.json()

    const responseSchema = ApiListResponseSchema<z.ZodType<T>>(dataSchema)

    const parsedData = responseSchema.parse(data)

    const results = parsedData.results.map((result: T) => result)

    if (parsedData.next) {
        const nextResults: T[] = await withPagination<T>(parsedData.next, apiToken, dataSchema)
        return [...results, ...nextResults]
    }

    return results
}

export const hasScope = (scopes: string[], requiredScope: string) => {
    if (scopes.includes('*')) {
        return true
    }

    // if read scoped required, and write present, return true
    if (
        requiredScope.endsWith(':read') &&
        scopes.includes(requiredScope.replace(':read', ':write'))
    ) {
        return true
    }

    return scopes.includes(requiredScope)
}

export const hasScopes = (scopes: string[], requiredScopes: string[]) => {
    return requiredScopes.every((scope) => hasScope(scopes, scope))
}
