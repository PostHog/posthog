import { HogFlowAction } from '../types'

const PERSON_PROPERTY_TEMPLATE =
    /^\s*\{\{\s*person\.properties(?:\.([\w$-]+)|\[\s*'([^'\\]+)'\s*\]|\[\s*"([^"\\]+)"\s*\])\s*\}\}\s*$/

/** The person property the To field reads, or null for a fixed address or any other template. */
export function recipientEmailProperty(to: string | undefined): string | null {
    const match = to?.match(PERSON_PROPERTY_TEMPLATE)
    return match?.[1] ?? match?.[2] ?? match?.[3] ?? null
}

/** The distinct person properties the workflow's email steps send to. */
export function recipientEmailProperties(workflow?: { actions?: HogFlowAction[] } | null): string[] {
    const properties = (workflow?.actions ?? [])
        .filter((action) => action.type === 'function_email')
        .map((action) => recipientEmailProperty((action as any)?.config?.inputs?.email?.value?.to?.email))
        .filter((property): property is string => property !== null)
    return [...new Set(properties)].sort()
}
