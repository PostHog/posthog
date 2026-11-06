import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
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
        properties: [{ key: 'plan', value: 'pro', operator: 'exact', type: 'person' }],
    },
}
const signedUpEntry = {
    filters: { events: [{ id: 'signed_up', name: 'signed_up', type: 'events', order: 0 }] },
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
        unmountWorkflowLogic = workflowLogic(LOGIC_PROPS).mount()
    })

    afterEach(() => {
        unmountWorkflowLogic?.()
        unmountWorkflowLogic = null
        cleanup()
    })

    function renderEditor(allEntriesEnabled: boolean): jest.Mock {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.WORKFLOWS_GOAL_EVENT_ENTRIES]: allEntriesEnabled,
        })
        const onChange = jest.fn()
        const conversion: ConversionGoalValue = { filters: [], events: [downloadedFileEntry, signedUpEntry] }
        render(
            <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
                <ConversionGoalEditor conversion={conversion} onChange={onChange} pageKey="goal" />
            </BindLogic>
        )
        return onChange
    }

    it.each([
        {
            flag: 'on',
            allEntriesEnabled: true,
            firstEntryProperties: downloadedFileEntry.filters.properties,
            otherEntries: [signedUpEntry],
        },
        { flag: 'off', allEntriesEnabled: false, firstEntryProperties: undefined, otherEntries: [] },
    ])(
        'with the flag $flag, an event edit writes the expected entries',
        async ({ allEntriesEnabled, firstEntryProperties, otherEntries }) => {
            const onChange = renderEditor(allEntriesEnabled)

            fireEvent.click(screen.getByTestId('more-button-1'))
            fireEvent.click(await screen.findByTestId('delete-prop-filter-1'))

            const [firstEntry, ...restEntries] = onChange.mock.lastCall[0].events
            expect(Object.keys(firstEntry)).toEqual(['filters'])
            expect(firstEntry.filters.events).toEqual([downloadedFileEntry.filters.events[0]])
            expect(firstEntry.filters.properties).toEqual(firstEntryProperties)
            expect(restEntries).toEqual(otherEntries)
            expect(screen.queryByText('signed_up') !== null).toBe(allEntriesEnabled)
        }
    )

    it("shows an entry's own property filters and removes one from that entry only", () => {
        const onChange = renderEditor(true)

        const propertyFilter = screen.getByText(/plan/).closest('.PropertyFilterButton') as HTMLElement
        fireEvent.click(within(propertyFilter).getByRole('button'))

        expect(onChange).toHaveBeenLastCalledWith(
            expect.objectContaining({
                events: [{ filters: { ...downloadedFileEntry.filters, properties: [] } }, signedUpEntry],
            })
        )
    })
})
