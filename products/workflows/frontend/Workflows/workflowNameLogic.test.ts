import { act, render, screen } from '@testing-library/react'
import { createElement } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowNameLogic } from './workflowNameLogic'

describe('workflowNameLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': ({ params }) =>
                    params.id === 'deleted'
                        ? [404, { detail: 'Not found.' }]
                        : [200, { id: params.id, name: `Workflow ${params.id}` }],
            },
        })
        initKeaTests()
        lemonToast.dismiss()
        render(createElement(jest.requireActual('react-toastify').ToastContainer))
    })

    const resolvedName = async (id: string): Promise<string | null> => {
        const logic = workflowNameLogic({ id })
        logic.mount()
        await act(async () => {
            await logic.asyncActions.loadWorkflow()
        })
        return logic.values.workflow?.name ?? null
    }

    it('resolves each cited workflow by its own id', async () => {
        expect(await resolvedName('flow-a')).toBe('Workflow flow-a')
        expect(await resolvedName('flow-b')).toBe('Workflow flow-b')
    })

    it('resolves a deleted workflow to nothing, without an error toast', async () => {
        expect(await resolvedName('deleted')).toBeNull()

        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
        expect(screen.queryByText(/Not found/)).toBeNull()
    })
})
