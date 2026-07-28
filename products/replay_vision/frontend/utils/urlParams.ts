/** CSV + sort-token URL param helpers shared by the scanners list and the observations table. */
import type { Sorting } from 'lib/lemon-ui/LemonTable'

/** LemonTable's `Sorting` with the column key narrowed to the caller's sortable-key union. */
export interface UrlSorting<K extends string = string> extends Sorting {
    columnKey: K
}

/** CSV join for URL params; an empty selection omits the param entirely. */
export const csvParam = (values: string[]): string | undefined => (values.length > 0 ? values.join(',') : undefined)

/** CSV split tolerant of the router coercing a single numeric param to a number; optional allowlist. */
export function parseCsvParam<T extends string>(value: unknown, validValues?: readonly T[]): T[] {
    const raw = typeof value === 'string' ? value : typeof value === 'number' ? String(value) : ''
    if (raw.length === 0) {
        return []
    }
    const parsed = raw
        .split(',')
        .map((v) => v.trim())
        .filter((v) => v.length > 0) as T[]
    return validValues ? parsed.filter((v) => validValues.includes(v)) : parsed
}

/** `-`-prefixed sort token, or undefined when the sort matches `defaultSort` (keeps the URL clean). */
export function serializeSortParam(sort: UrlSorting | null, defaultSort?: UrlSorting): string | undefined {
    if (!sort || (defaultSort && sort.columnKey === defaultSort.columnKey && sort.order === defaultSort.order)) {
        return undefined
    }
    return `${sort.order === -1 ? '-' : ''}${sort.columnKey}`
}

/** Parse a `-`-prefixed sort token; an optional `resolveKey` validates and narrows the column key. */
export function parseSortParam<K extends string>(
    value: unknown,
    resolveKey?: (key: string) => K | null
): UrlSorting<K> | null {
    if (typeof value !== 'string' || value.length === 0) {
        return null
    }
    const descending = value.startsWith('-')
    const rawKey = descending ? value.slice(1) : value
    if (!rawKey) {
        return null
    }
    const columnKey = resolveKey ? resolveKey(rawKey) : (rawKey as K)
    if (!columnKey) {
        return null
    }
    return { columnKey, order: descending ? -1 : 1 }
}
