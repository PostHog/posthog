/**
 * `<MemoryTables>` — read-only viewer for the agent's tabular-reference
 * tables (the `@posthog/table-*` JSONL tables: seen-sets, archive logs, etc.).
 * Sits behind the Files|Tables toggle in the memory tab. Table list on the
 * left; the selected table's rows render as a grid on the right.
 */

'use client'

import { useState } from 'react'

import { useSessionTeamId } from '@/components/session-context'
import { listTables, readTable } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

import { RefreshIndicator } from './RefreshIndicator'

function fmtBytes(n: number): string {
    if (n < 1024) {
        return `${n} B`
    }
    if (n < 1024 * 1024) {
        return `${(n / 1024).toFixed(1)} KB`
    }
    return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function cell(v: unknown): string {
    if (v === null || v === undefined) {
        return ''
    }
    if (typeof v === 'object') {
        return JSON.stringify(v)
    }
    return String(v)
}

export function MemoryTables({ slug }: { slug: string }): React.ReactElement {
    const teamId = useSessionTeamId()!
    const [selected, setSelected] = useState<string | null>(null)

    const tables = useResource(() => listTables(teamId, slug), [teamId, slug], { pollMs: 10000 })
    const rows = useResource(
        () => (selected ? readTable(teamId, slug, selected, { limit: 500 }) : Promise.resolve(null)),
        [teamId, slug, selected],
        { pollMs: selected ? 10000 : undefined }
    )

    const list = tables.data?.tables ?? []
    // Column union across the returned rows — tables are schema-light.
    const data = rows.data
    const columns = data ? Array.from(new Set(data.rows.flatMap((r) => Object.keys(r)))) : []

    return (
        <div className="grid h-full grid-cols-[minmax(200px,260px)_minmax(0,1fr)] divide-x divide-border">
            <aside className="flex min-h-0 flex-col overflow-y-auto">
                <div className="flex items-center justify-between border-b border-border px-3 py-2">
                    <span className="text-[0.625rem] uppercase tracking-wide text-muted-foreground">Tables</span>
                    <RefreshIndicator resource={tables} intervalMs={0} />
                </div>
                {tables.loading && !tables.data ? (
                    <div className="p-3 text-xs text-muted-foreground">Loading…</div>
                ) : list.length === 0 ? (
                    <div className="p-3 text-xs text-muted-foreground">
                        No tables yet. The agent creates them on first `table-append`.
                    </div>
                ) : (
                    <ul className="py-1">
                        {list.map((t) => (
                            <li key={t.name}>
                                <button
                                    type="button"
                                    onClick={() => setSelected(t.name)}
                                    className={`flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent ${
                                        selected === t.name ? 'bg-muted font-medium' : ''
                                    }`}
                                >
                                    <code className="truncate font-mono">{t.name}</code>
                                    <span className="shrink-0 text-[0.625rem] text-muted-foreground">
                                        {fmtBytes(t.size)}
                                    </span>
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
            </aside>

            <main className="min-h-0 overflow-auto">
                {!selected ? (
                    <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
                        Pick a table to view its rows.
                    </div>
                ) : rows.loading && !rows.data ? (
                    <div className="p-6 text-sm text-muted-foreground">Loading…</div>
                ) : rows.error ? (
                    <div className="p-6 text-sm text-destructive-foreground">Failed to load: {rows.error.message}</div>
                ) : data ? (
                    <div className="flex h-full flex-col">
                        <header className="flex items-center justify-between gap-3 border-b border-border bg-muted/10 px-3 py-2">
                            <code className="text-[0.8125rem] font-mono">{data.name}</code>
                            <span className="text-xs text-muted-foreground">
                                {data.returned} of {data.total} rows
                                {data.total > data.returned ? ` (showing first ${data.limit})` : ''}
                            </span>
                        </header>
                        <div className="min-h-0 flex-1 overflow-auto">
                            {data.rows.length === 0 ? (
                                <div className="p-6 text-sm text-muted-foreground">Table is empty.</div>
                            ) : (
                                <table className="w-full border-collapse text-[0.75rem]">
                                    <thead className="sticky top-0 bg-muted/40">
                                        <tr>
                                            {columns.map((c) => (
                                                <th
                                                    key={c}
                                                    className="border-b border-border px-2 py-1 text-left font-mono font-medium"
                                                >
                                                    {c}
                                                </th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.rows.map((r, i) => (
                                            <tr key={i} className="even:bg-muted/10">
                                                {columns.map((c) => (
                                                    <td
                                                        key={c}
                                                        className="max-w-[28rem] truncate border-b border-border/50 px-2 py-1 font-mono"
                                                        title={cell(r[c])}
                                                    >
                                                        {cell(r[c])}
                                                    </td>
                                                ))}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </div>
                    </div>
                ) : null}
            </main>
        </div>
    )
}
