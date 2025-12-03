/**
 * Updates an optional name field in an object, properly handling deletion when empty
 */
export function updateOptionalName<T>(obj: T & { name?: string }, name: string | undefined): T & { name?: string } {
    const updated = { ...obj }
    if (name) {
        updated.name = name
    } else {
        delete updated.name
    }
    return updated
}

/**
 * Updates an item in an array by index with an optional name field
 */
export function updateItemWithOptionalName<T>(
    items: Array<T & { name?: string }>,
    index: number,
    name: string | undefined
): Array<T & { name?: string }> {
    return items.map((item, i) => {
        if (i !== index) {
            return item
        }
        return updateOptionalName(item, name)
    })
}
