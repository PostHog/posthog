import { Suspense } from 'react'

import { NotebookComponentRenderProps } from 'lib/components/MarkdownNotebook/types'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'

const NotebookInvestigation = lazyWithRetry(() =>
    import('./NotebookInvestigation').then(({ NotebookInvestigation }) => ({ default: NotebookInvestigation }))
)

export function LazyNotebookInvestigation(props: NotebookComponentRenderProps): JSX.Element {
    return (
        <Suspense fallback={<Spinner />}>
            <NotebookInvestigation {...props} />
        </Suspense>
    )
}
