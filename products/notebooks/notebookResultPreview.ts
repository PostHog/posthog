export interface NotebookResultPreviewSource<Row extends unknown[]> {
    columns?: string[]
    types?: string[][]
    row_count?: number
    first_page?: Row[]
    has_more?: boolean
    stdout?: string
    stderr?: string
}

export function notebookResultPreview<Row extends unknown[]>(
    result: NotebookResultPreviewSource<Row>
): {
    columns: string[]
    types: [string, string][]
    row_count: number
    first_page: Row[]
    has_more: boolean
    stdout: string
    stderr: string
    previewOnly: true
} {
    const rows: Row[] = []
    for (const row of (result.first_page ?? []).slice(0, 5)) {
        if (new TextEncoder().encode(JSON.stringify([...rows, row])).length > 8192) {
            break
        }
        rows.push(row)
    }
    return {
        columns: result.columns ?? [],
        types: (result.types ?? []).map(([name, type]) => [name ?? '', type ?? '']),
        row_count: result.row_count ?? 0,
        first_page: rows,
        has_more: !!result.has_more || (result.row_count ?? 0) > rows.length,
        stdout: (result.stdout ?? '').slice(0, 2048),
        stderr: (result.stderr ?? '').slice(0, 2048),
        previewOnly: true,
    }
}
