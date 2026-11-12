import { z } from 'zod'

import { hasCapability, hasUiApp } from './executor'
import { CATALOG_SCHEMA_VERSION, type CatalogEntry, CatalogDocumentSchema, CatalogEntrySchema } from './schema'

export interface DroppedCatalogTool {
    name: string
    reason: string
}

export type LoadedCatalog =
    | { ok: true; build: string | null; entries: CatalogEntry[]; dropped: DroppedCatalogTool[] }
    | { ok: false; reason: string }

function entryName(raw: unknown): string {
    const name = (raw as { name?: unknown } | null)?.name
    return typeof name === 'string' ? name : '(unnamed)'
}

function firstIssue(error: z.ZodError): string {
    const issue = error.issues[0]
    if (!issue) {
        return 'it does not match the catalog format'
    }
    if (issue.code === 'unrecognized_keys') {
        return `unknown field ${[...issue.path, ...issue.keys].join('.')}`
    }
    return `${issue.path.join('.') || 'entry'}: ${issue.message}`
}

// An entry this build can't run exactly as the server meant it is dropped, never adapted, so hog
// keeps running its compiled-in tool for that name. `reserved` holds the names hand-written tools
// own, which a catalog entry must not replace.
export function loadCatalog(raw: unknown, reserved: ReadonlySet<string> = new Set()): LoadedCatalog {
    const document = CatalogDocumentSchema.safeParse(raw)
    if (!document.success) {
        return { ok: false, reason: 'the catalog does not match the catalog format' }
    }
    if (document.data.schemaVersion !== CATALOG_SCHEMA_VERSION) {
        return {
            ok: false,
            reason: `the catalog uses format ${document.data.schemaVersion}, and this hog reads format ${CATALOG_SCHEMA_VERSION}`,
        }
    }

    const entries: CatalogEntry[] = []
    const dropped: DroppedCatalogTool[] = []
    const seen = new Set<string>()
    for (const rawEntry of document.data.tools) {
        const parsed = CatalogEntrySchema.safeParse(rawEntry)
        if (!parsed.success) {
            dropped.push({ name: entryName(rawEntry), reason: firstIssue(parsed.error) })
            continue
        }

        const entry = parsed.data
        const missing = entry.requires.filter((capability) => !hasCapability(capability))
        if (missing.length > 0) {
            dropped.push({ name: entry.name, reason: `needs ${missing.join(', ')}, which this hog doesn't have` })
            continue
        }
        if (entry.uiApp !== null && !hasUiApp(entry.uiApp)) {
            dropped.push({ name: entry.name, reason: `needs the UI app ${entry.uiApp}, which this hog doesn't have` })
            continue
        }
        if (reserved.has(entry.name) || seen.has(entry.name)) {
            dropped.push({ name: entry.name, reason: 'another tool already has this name' })
            continue
        }
        seen.add(entry.name)
        entries.push(entry)
    }
    return { ok: true, build: document.data.build, entries, dropped }
}
