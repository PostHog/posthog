import { act, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
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

    const mounted = async (id: string): Promise<ReturnType<typeof workflowNameLogic.build>> => {
        const logic = workflowNameLogic({ id })
        logic.mount()
        await act(async () => {
            await expectLogic(logic).toFinishAllListeners()
        })
        return logic
    }

    it('resolves each cited workflow by its own id', async () => {
        const first = await mounted('flow-a')
        const second = await mounted('flow-b')

        expect([first.values.workflow?.name, second.values.workflow?.name]).toEqual([
            'Workflow flow-a',
            'Workflow flow-b',
        ])
    })

    it('resolves a deleted workflow to nothing, without an error toast', async () => {
        expect((await mounted('deleted')).values.workflow).toBeNull()

        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
        expect(screen.queryByText(/Not found/)).toBeNull()
    })
})
