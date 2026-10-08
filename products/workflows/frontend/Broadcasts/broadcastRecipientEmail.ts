const PERSON_PROPERTY_TEMPLATE = /^\s*\{\{\s*person\.properties\.([\w$-]+)\s*\}\}\s*$/

/** The person property the To field reads, or null for a fixed address or any other template. */
export function recipientEmailProperty(to: string | undefined): string | null {
    return to?.match(PERSON_PROPERTY_TEMPLATE)?.[1] ?? null
}
