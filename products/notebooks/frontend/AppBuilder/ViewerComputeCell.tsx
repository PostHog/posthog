import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'
import { objectsEqual } from 'lib/utils/objects'
import type { NotebookVariable } from 'scenes/notebooks/Notebook/notebookVariables'

import { notebookAppViewerLogic, type ViewerProps } from './notebookAppViewerLogic'

export function ViewerComputeCell({
    viewer,
    cell,
    variables,
    saved,
}: {
    viewer: ViewerProps
    cell: NotebookComponentBlockNode
    variables: NotebookVariable[]
    saved: JSX.Element
}): JSX.Element {
    const { privateCells } = useValues(notebookAppViewerLogic(viewer))
    const { runPrivateCell } = useActions(notebookAppViewerLogic(viewer))
    const { result, loading, error } = privateCells[cell.id] ?? {}
    const python = cell.tagName === 'PythonV2'
    return (
        <div>
            <div className="flex flex-wrap gap-2 items-center mb-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => runPrivateCell(cell.id, python ? 'python' : 'connected_sql')}
                    loading={loading}
                >
                    {python ? 'Run Python for me' : 'Run query for me'}
                </LemonButton>
                <span className="text-secondary">
                    {result && !objectsEqual(variables, result.inputs)
                        ? 'Inputs changed. Run again to update this result.'
                        : python
                          ? 'Runs in a private sandbox with your current inputs.'
                          : 'Uses your access to the connected data source.'}
                </span>
            </div>
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            {result?.data.rows && result.data.columns ? (
                <LemonTable
                    dataSource={result.data.rows}
                    pagination={{ pageSize: 20 }}
                    virtualizedColumnWidth={160}
                    columns={result.data.columns.map((title, index) => ({
                        title,
                        key: String(index),
                        render: (_, row) => String(row[index] ?? ''),
                    }))}
                />
            ) : result ? (
                <pre className="whitespace-pre-wrap">{result.data.text || 'Calculation finished.'}</pre>
            ) : (
                saved
            )}
        </div>
    )
}
