import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'

import { WorkflowLogicProps, workflowLogic } from '../../../workflowLogic'
import { ConversionGoalEditor, ConversionGoalValue } from './ConversionGoalEditor'

const LOGIC_PROPS: WorkflowLogicProps = { id: 'new' }

const downloadedFileEntry = {
    filters: {
        events: [
            { id: 'downloaded_file', name: 'downloaded_file', type: 'events', order: 0 },
            { id: 'opened_invite', name: 'opened_invite', type: 'events', order: 1 },
        ],
    },
}
const signedUpEntry = {
    filters: {
        events: [{ id: 'signed_up', name: 'signed_up', type: 'events', order: 0 }],
        properties: [{ key: 'plan', value: 'pro', operator: 'exact', type: 'person' }],
    },
}

describe('ConversionGoalEditor', () => {
    let unmountWorkflowLogic: (() => void) | null = null

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': { results: [], count: 0 },
                '/api/projects/:team/actions': { results: [] },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_GOAL_EVENT_ENTRIES]: true })
        unmountWorkflowLogic = workflowLogic(LOGIC_PROPS).mount()
    })

    afterEach(() => {
        unmountWorkflowLogic?.()
        unmountWorkflowLogic = null
        cleanup()
    })

    it('shows every stored event entry and keeps the others when one is edited', async () => {
        const onChange = jest.fn()
        const conversion: ConversionGoalValue = { filters: [], events: [downloadedFileEntry, signedUpEntry] }
        render(
            <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
                <ConversionGoalEditor conversion={conversion} onChange={onChange} pageKey="goal" />
            </BindLogic>
        )

        fireEvent.click(screen.getByTestId('more-button-1'))
        fireEvent.click(await screen.findByTestId('delete-prop-filter-1'))

        expect(onChange).toHaveBeenLastCalledWith(
            expect.objectContaining({
                events: [
                    { filters: expect.objectContaining({ events: [downloadedFileEntry.filters.events[0]] }) },
                    signedUpEntry,
                ],
            })
        )
        expect(screen.getByText('signed_up')).toBeInTheDocument()
    })
})
