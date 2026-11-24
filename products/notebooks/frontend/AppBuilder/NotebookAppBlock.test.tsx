import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { lemonToast } from '@posthog/lemon-ui'

import * as chunkLoader from 'lib/utils/retryImport'
import * as stableChunks from 'lib/utils/stableChunks'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { NotebookAppBlock } from './NotebookAppBlock'
import { newAppBlock } from './notebookAppLayout'

it('offers to reload when the drop-off recordings cannot load', async () => {
    initKeaTests()
    const error = new Error('Failed to fetch dynamically imported module')
    const showError = jest.spyOn(lemonToast, 'error')
    const reload = jest.spyOn(stableChunks, 'reloadAfterChunkLoadError').mockImplementation(() => {})
    render(
        <NotebookAppBlock
            block={newAppBlock('cell', 'overview', { node_id: 'funnel' })}
            cell={{
                id: 'funnel',
                type: 'component',
                tagName: 'Query',
                props: {
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.FunnelsQuery,
                            series: ['entry', 'adoption'].map((event) => ({ kind: NodeKind.EventsNode, event })),
                        },
                    },
                },
            }}
            stale={false}
            variables={[]}
            canInteract={false}
            onInput={() => {}}
            renderOutput={() => <div />}
        />
    )
    jest.spyOn(chunkLoader, 'retryImport').mockRejectedValueOnce(error)
    fireEvent.click(screen.getByTestId('notebook-app-dropoff-recordings'))
    await waitFor(() => expect(showError).toHaveBeenCalled())
    const action = showError.mock.lastCall?.[1]?.button
    expect(action?.label).toBe('Reload')
    action?.action()
    expect(reload).toHaveBeenCalledWith(error)
})
