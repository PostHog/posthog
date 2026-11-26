import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import { readableErrorMessage } from 'lib/api-error'
import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'
import { objectsEqual } from 'lib/utils/objects'
import type { NotebookVariable } from 'scenes/notebooks/Notebook/notebookVariables'

import { notebooksAppComputeCreate, notebooksAppDraftComputeCreate } from '../generated/api'
import type { NotebookAppComputeResultApi } from '../generated/api.schemas'
import type { ViewerProps } from './notebookAppViewerLogic'

function computationKind(cell: NotebookComponentBlockNode): 'python' | 'connected_sql' | 'dataframe_sql' {
    if (cell.tagName === 'PythonV2') {
        return 'python'
    }
    return cell.props.connectionId ? 'connected_sql' : 'dataframe_sql'
}

export function ViewerComputeCell({
    viewer,
    revision,
    cell,
    variables,
    saved,
}: {
    viewer: ViewerProps
    revision: number
    cell: NotebookComponentBlockNode
    variables: NotebookVariable[]
    saved: JSX.Element
}): JSX.Element {
    const [result, setResult] = useState<{ data: NotebookAppComputeResultApi; inputs: NotebookVariable[] }>()
    const [loading, setLoading] = useState(false)
    const [failure, setFailure] = useState<string>()
    const controller = useRef<AbortController | null>(null)
    useEffect(() => () => controller.current?.abort(), [])
    const kind = computationKind(cell)

    async function run(): Promise<void> {
        controller.current?.abort()
        const request = new AbortController()
        controller.current = request
        setLoading(true)
        setFailure(undefined)
        try {
            const body = { node_id: cell.id, revision, variables }
            const options = { signal: request.signal }
            const data = viewer.draft
                ? await notebooksAppDraftComputeCreate(
                      viewer.project,
                      viewer.shortId,
                      { ...body, layout: viewer.draft.layout },
                      options
                  )
                : await notebooksAppComputeCreate(viewer.project, viewer.shortId, body, options)
            if (!request.signal.aborted) {
                setResult({ data, inputs: variables })
                posthog.capture('notebook app viewer calculation ran', {
                    short_id: viewer.shortId,
                    cell_type: kind,
                })
            }
        } catch (error) {
            if (!request.signal.aborted) {
                setFailure(
                    readableErrorMessage(error) ||
                        'Could not run this calculation. Check your data access and try again.'
                )
            }
        } finally {
            if (!request.signal.aborted) {
                setLoading(false)
            }
        }
    }
    return (
        <div>
            <div className="flex flex-wrap gap-2 items-center mb-2">
                <LemonButton type="secondary" size="small" onClick={() => void run()} loading={loading}>
                    {kind === 'python' ? 'Run Python for me' : 'Run query for me'}
                </LemonButton>
                <span className="text-secondary">
                    {result && !objectsEqual(variables, result.inputs)
                        ? 'Inputs changed. Run again to update this result.'
                        : kind !== 'connected_sql'
                          ? 'Runs in a private sandbox with your current inputs.'
                          : 'Uses your access to the connected data source.'}
                </span>
            </div>
            {failure && <LemonBanner type="error">{failure}</LemonBanner>}
            {result?.data.rows && result.data.columns ? (
                <LemonTable
                    dataSource={result.data.rows}
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
