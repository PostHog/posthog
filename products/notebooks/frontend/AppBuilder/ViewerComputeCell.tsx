import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'
import { objectsEqual } from 'lib/utils/objects'

import type { NotebookAppComputeResultApi } from '../generated/api.schemas'
import { notebookAppViewerLogic, type ViewerProps } from './notebookAppViewerLogic'

export function ViewerComputeControls({
    viewer,
    cell,
}: {
    viewer: ViewerProps
    cell: NotebookComponentBlockNode
}): JSX.Element | null {
    const { privateCells, variables, nativeOutputIds } = useValues(notebookAppViewerLogic(viewer))
    const { runPrivateCell } = useActions(notebookAppViewerLogic(viewer))
    if (
        cell.tagName === 'SQLV2' &&
        !cell.props.connectionId &&
        (!nativeOutputIds || nativeOutputIds.includes(cell.id))
    ) {
        return null
    }
    const { result, loading, error } = privateCells[cell.id] ?? {}
    const kind = cell.tagName === 'PythonV2' ? 'python' : cell.props.connectionId ? 'connected_sql' : 'dataframe_sql'
    const python = cell.tagName === 'PythonV2'
    return (
        <div>
            <div className="flex flex-wrap gap-2 items-center mb-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => runPrivateCell(cell.id, kind)}
                    loading={loading}
                >
                    {python ? 'Run Python for me' : 'Run query for me'}
                </LemonButton>
                <span className="text-secondary">
                    {result && !objectsEqual(variables, result.inputs)
                        ? 'Inputs changed. Run again to update this result.'
                        : kind !== 'connected_sql'
                          ? 'Runs in a private sandbox with your current inputs.'
                          : 'Uses your access to the connected data source.'}
                </span>
            </div>
            {error && <LemonBanner type="error">{error}</LemonBanner>}
        </div>
    )
}

export function ViewerComputeResult({ data }: { data: NotebookAppComputeResultApi }): JSX.Element {
    return data.rows && data.columns ? (
        <LemonTable
            dataSource={data.rows}
            pagination={{ pageSize: 20 }}
            virtualizedColumnWidth={160}
            columns={data.columns.map((title, index) => ({
                title,
                key: String(index),
                render: (_, row) => String(row[index] ?? ''),
            }))}
        />
    ) : (
        <pre className="whitespace-pre-wrap">{data.text || 'Calculation finished.'}</pre>
    )
}
