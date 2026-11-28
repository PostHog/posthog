import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { lemonToast } from '@posthog/lemon-ui'

import * as chunkLoader from 'lib/utils/retryImport'
import * as stableChunks from 'lib/utils/stableChunks'
import { toNotebookPropValue } from 'scenes/notebooks/Notebook/markdownNotebookV2'

import { NodeKind } from '~/queries/schema/schema-general'
import type { FunnelsFilter } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { NotebookAppBlock } from './NotebookAppBlock'
import { newAppBlock } from './notebookAppLayout'

afterEach(cleanup)

function renderFunnel(funnelsFilter?: FunnelsFilter): void {
    initKeaTests()
    render(
        <NotebookAppBlock
            block={newAppBlock('cell', 'overview', { node_id: 'funnel' })}
            cell={{
                id: 'funnel',
                type: 'component',
                tagName: 'Query',
                props: {
                    query: toNotebookPropValue({
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.FunnelsQuery,
                            funnelsFilter,
                            series: ['entry', 'adoption'].map((event) => ({ kind: NodeKind.EventsNode, event })),
                        },
                    }),
                },
            }}
            stale={false}
            variables={[]}
            canInteract={false}
            onInput={() => {}}
            renderOutput={() => <div />}
        />
    )
}

it.each([
    ['unique sessions', { funnelAggregateByHogQL: 'properties.$session_id' }, true],
    ['order IDs', { funnelAggregateByHogQL: 'properties.order_id' }, false],
    ['custom aggregation targets', { customAggregationTarget: true }, false],
] as const)('offers a recording drill-down for %s according to the funnel aggregation', (_name, filter, visible) => {
    renderFunnel(filter)
    const button = screen.queryByTestId('notebook-app-dropoff-recordings')
    expect(Boolean(button)).toBe(visible)
})

it('offers to reload when the drop-off recordings cannot load', async () => {
    const error = new Error('Failed to fetch dynamically imported module')
    const showError = jest.spyOn(lemonToast, 'error')
    const reload = jest.spyOn(stableChunks, 'reloadAfterChunkLoadError').mockImplementation(() => {})
    renderFunnel()
    jest.spyOn(chunkLoader, 'retryImport').mockRejectedValueOnce(error)
    fireEvent.click(screen.getByTestId('notebook-app-dropoff-recordings'))
    await waitFor(() => expect(showError).toHaveBeenCalled())
    const action = showError.mock.lastCall?.[1]?.button
    expect(action?.label).toBe('Reload')
    action?.action()
    expect(reload).toHaveBeenCalledWith(error)
})
