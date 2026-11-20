import { describe, expect, it } from 'vitest'

import { getToolDefinitions } from '@/tools/toolDefinitions'

// Read-only connections and client write gates trust `readOnlyHint`, so each read-only tool needing a write scope is reviewed here.
const REVIEWED_READ_ONLY_WRITE_SCOPE_TOOLS: Record<string, string> = {
    'external-data-schemas-destinations-retrieve':
        'GET; the write scope belongs to the PATCH on the same action. It may create the default warehouse row, which every sync creates anyway',
    'external-data-sources-destinations-retrieve': 'GET; the write scope belongs to the PATCH on the same action',
    'feature-flags-copy-dependencies-check': 'Previews a copy and saves nothing; scoped like the copy it previews',
    'file-download-batch-exports-count-rows-create': 'Counts rows only; the write scope guards query cost',
    'inbox-my-settings-get': 'GET; the view applies user:write to every method',
    'proxy-diagnose': 'Probes the proxy domain an org admin registered and saves nothing',
    'scout-report-check-list': 'GET; the write scope gates the report channel',
    'scout-report-checks-list': 'Deprecated alias of scout-report-check-list',
    'scout-trial-list': 'GET; the write scope gates private trials',
    'scout-trial-report': 'GET; the write scope gates private trials',
    'scout-trial-setup': 'GET; the write scope gates private trials',
    'vision-requests-get': 'GET; the write scope gates scanner output',
    'external-data-schemas-incremental-fields-create':
        'PR #138684 relabels it as a write, so its entry goes when that PR merges',
    'external-data-sources-check-cdc-prerequisites-create':
        'PR #138684 relabels it as a write, so its entry goes when that PR merges',
    'external-data-sources-db-schema': 'PR #138684 relabels it as a write, so its entry goes when that PR merges',
}

describe('read-only tools that require a write scope', () => {
    const definitions = getToolDefinitions()
    const readOnlyWithWriteScope = Object.entries(definitions)
        .filter(([, definition]) => definition.annotations.readOnlyHint)
        .filter(([, definition]) => (definition.required_scopes ?? []).some((scope) => scope.endsWith(':write')))
        .map(([name]) => name)
        .filter((name) => !(name.endsWith('-prepare') && definitions[name.replace(/-prepare$/, '-execute')]))

    it('are all reviewed', () => {
        expect(readOnlyWithWriteScope.filter((name) => !(name in REVIEWED_READ_ONLY_WRITE_SCOPE_TOOLS))).toEqual([])
    })

    it('leave no stale review entries', () => {
        expect(
            Object.keys(REVIEWED_READ_ONLY_WRITE_SCOPE_TOOLS).filter((name) => !readOnlyWithWriteScope.includes(name))
        ).toEqual([])
    })
})
