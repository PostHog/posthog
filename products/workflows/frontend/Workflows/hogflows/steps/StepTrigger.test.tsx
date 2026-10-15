import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Node } from '@xyflow/react'
import { BindLogic } from 'kea'

import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { mockActionDefinition, mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { StepTriggerConfiguration } from './StepTrigger'

type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

const LOGIC_PROPS: WorkflowLogicProps = { id: 'new' }

describe('StepTriggerConfiguration', () => {
    let unmountWorkflowLogic: (() => void) | null = null

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/actions': { results: [mockActionDefinition] },
                '/api/environments/:team/persons/properties': [],
                '/api/environments/:team/events/values': { results: [], refreshing: false },
                '/api/environments/:team_id/quick_filters/': { results: [] },
                '/api/projects/:team/hog_flows/inbox_report_access/': { can_use_inbox_reports: false },
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        propertyDefinitionsModel.mount()
        recentTaxonomicFiltersLogic.mount()
        unmountWorkflowLogic = workflowLogic(LOGIC_PROPS).mount()
    })

    afterEach(() => {
        unmountWorkflowLogic?.()
        unmountWorkflowLogic = null
        cleanup()
    })

    function renderTrigger(properties: NonNullable<HogFlowAction['filters']>['properties']): void {
        const action = {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            config: { type: 'event', filters: { events: [], properties } },
        } as TriggerAction
        render(
            <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
                <StepTriggerConfiguration node={{ id: action.id, data: action } as Node<TriggerAction>} />
            </BindLogic>
        )
    }

    it('keeps a stored global property filter when the trigger events change', async () => {
        const properties = [{ type: 'hogql', key: "properties.plan = 'pro'" }] as NonNullable<
            HogFlowAction['filters']
        >['properties']
        renderTrigger(properties)

        fireEvent.click(screen.getByText('Add trigger event'))

        await waitFor(() => {
            const trigger = workflowLogic(LOGIC_PROPS).values.workflow.trigger as TriggerAction['config']
            expect(trigger.type).toEqual('event')
            expect((trigger as Extract<TriggerAction['config'], { type: 'event' }>).filters?.properties).toEqual(
                properties
            )
        })
    })

    it('shows a global HogQL property filter stored on the event trigger', async () => {
        renderTrigger([{ type: 'hogql', key: "properties.plan = 'pro'" }])

        expect(screen.getByText('Additional filters')).toBeInTheDocument()
        await waitFor(() => {
            expect(screen.getByText("properties.plan = 'pro'")).toBeInTheDocument()
        })
    })

    function enableInboxReportTrigger(): void {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOW_INBOX_REPORT_TRIGGER], {
            [FEATURE_FLAGS.WORKFLOW_INBOX_REPORT_TRIGGER]: true,
        })
    }

    function inboxReportTile(): HTMLElement | null {
        return screen.getByText('Inbox report ready').closest('button')
    }

    it.each([
        [
            'without access to Tasks',
            { can_use_inbox_reports: false },
            'You need viewer access to Tasks to use Inbox reports in workflows.',
        ],
        [
            'whose access to Tasks could not be checked',
            () => [500, { detail: 'Server error' }],
            "Couldn't check your access to Tasks. Reopen the trigger to try again.",
        ],
    ])('disables the Inbox report ready tile for someone %s', async (_name, accessResponse, disabledReason) => {
        useMocks({ get: { '/api/projects/:team/hog_flows/inbox_report_access/': accessResponse } })
        enableInboxReportTrigger()
        renderTrigger([])

        fireEvent.click(screen.getByText('Event'))
        await waitFor(() => {
            expect(inboxReportTile()).toHaveAttribute('aria-disabled', 'true')
        })
        fireEvent.click(screen.getByText('Inbox report ready'))

        expect(await screen.findByText(disabledReason)).toBeInTheDocument()
    })

    it('checks access to Tasks once when the trigger opens and keeps the tile disabled until it knows', async () => {
        let accessRequests = 0
        let grantAccess = (): void => {}
        useMocks({
            get: {
                '/api/projects/:team/hog_flows/inbox_report_access/': () => {
                    accessRequests += 1
                    return new Promise((resolve) => {
                        grantAccess = () => resolve({ can_use_inbox_reports: true })
                    })
                },
            },
        })
        enableInboxReportTrigger()
        renderTrigger([])
        await waitFor(() => expect(accessRequests).toEqual(1))

        fireEvent.click(screen.getByText('Event'))
        expect(inboxReportTile()).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(screen.getByText('Inbox report ready'))
        expect(await screen.findByText('Checking your access to Tasks...')).toBeInTheDocument()

        grantAccess()

        await waitFor(() => {
            expect(inboxReportTile()).not.toHaveAttribute('aria-disabled', 'true')
        })
        expect(accessRequests).toEqual(1)
    })
})
