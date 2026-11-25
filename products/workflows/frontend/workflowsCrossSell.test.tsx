import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'
import './Workflows/hogflows/registry/triggers/data_warehouse_table'
import './Workflows/hogflows/registry/triggers/surveys'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Node } from '@xyflow/react'
import { BindLogic } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SurveyEventName } from '~/types'

import { AfterClickingCard } from './Transactional/impact/AfterClickingCard'
import { emailImpactLogic } from './Transactional/impact/emailImpactLogic'
import { getRegisteredTriggerTypes } from './Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { HogFlowAction } from './Workflows/hogflows/types'
import { WorkflowLogicProps, workflowLogic } from './Workflows/workflowLogic'

type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

const WORKFLOW_PROPS: WorkflowLogicProps = { id: 'new' }

function renderTrigger(triggerType: string, config: TriggerAction['config']): void {
    const ConfigComponent = getRegisteredTriggerTypes().find((t) => t.value === triggerType)?.ConfigComponent
    if (!ConfigComponent) {
        throw new Error(`Trigger type ${triggerType} is not registered`)
    }
    const action = { id: 'trigger_node', type: 'trigger', name: 'Trigger', description: '', config } as TriggerAction
    render(
        <BindLogic logic={workflowLogic} props={WORKFLOW_PROPS}>
            <ConfigComponent node={{ id: action.id, data: action } as Node<TriggerAction>} />
        </BindLogic>
    )
}

const SURFACES = [
    {
        surface: 'the email impact tab',
        renderSurface: (): void => {
            render(
                <BindLogic logic={emailImpactLogic} props={{ workflowId: 'workflow-1' }}>
                    <AfterClickingCard />
                </BindLogic>
            )
        },
        link: 'Turn on session replay',
        product: 'session_replay',
        context: 'workflow_email_impact_turn_on_replay',
    },
    {
        surface: 'the survey trigger with no surveys',
        renderSurface: (): void =>
            renderTrigger('survey_response', {
                type: 'event',
                filters: {
                    events: [{ id: SurveyEventName.SENT, type: 'events', name: 'Survey sent' }],
                    properties: [{ key: '$survey_id', operator: 'is_set', type: 'event' }],
                },
            } as TriggerAction['config']),
        link: 'Create a survey',
        product: 'surveys',
        context: 'workflow_survey_trigger_create_survey',
    },
    {
        surface: 'the warehouse table trigger with no tables',
        renderSurface: (): void =>
            renderTrigger('data-warehouse-table', { type: 'data-warehouse-table' } as TriggerAction['config']),
        link: 'Set up a source',
        product: 'data_warehouse',
        context: 'workflow_warehouse_table_trigger_set_up_source',
    },
]

const CLICKS = [
    { click: 'a click', follow: (link: HTMLElement): boolean => fireEvent.click(link) },
    { click: 'a Cmd-click', follow: (link: HTMLElement): boolean => fireEvent.click(link, { metaKey: true }) },
    {
        click: 'a middle click',
        follow: (link: HTMLElement): boolean =>
            fireEvent(link, new MouseEvent('auxclick', { bubbles: true, cancelable: true, button: 1 })),
    },
]

const CASES = SURFACES.flatMap((surface) => CLICKS.map((click) => ({ ...surface, ...click })))

describe('cross-sell from workflows', () => {
    let intents: unknown[]
    let intentStatus: number
    let unhandledRejections: unknown[]
    const onUnhandledRejection = (reason: unknown): void => {
        unhandledRejections.push(reason)
    }
    let unmountWorkflowLogic: (() => void) | null = null

    beforeEach(() => {
        intents = []
        intentStatus = 201
        unhandledRejections = []
        process.on('unhandledRejection', onUnhandledRejection)
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/impact/': () => [200, null],
                '/api/projects/:team_id/surveys/': () => [200, { results: [], count: 0 }],
            },
            post: {
                '/api/projects/:team_id/query/:kind/': () => [200, { results: [], tables: {}, joins: [] }],
            },
            patch: {
                '/api/projects/:team_id/add_product_intent/': async ({ request }) => {
                    intents.push(await request.json())
                    return [intentStatus, intentStatus < 400 ? MOCK_DEFAULT_TEAM : { detail: 'Server error' }]
                },
            },
        })
        initKeaTests()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: false })
        unmountWorkflowLogic = workflowLogic(WORKFLOW_PROPS).mount()
    })

    afterEach(() => {
        process.off('unhandledRejection', onUnhandledRejection)
        unmountWorkflowLogic?.()
        unmountWorkflowLogic = null
        cleanup()
    })

    it.each(CASES)(
        'records a cross-sell intent when $click follows the link on $surface',
        async ({ renderSurface, link, follow, product, context }) => {
            renderSurface()

            follow(await screen.findByText(link))

            await waitFor(() => expect(intents).toHaveLength(1))
            expect(intents[0]).toEqual({
                product_type: product,
                intent_context: context,
                metadata: { from: 'workflows', to: product, type: 'cross_sell' },
            })
        }
    )

    it('records nothing on a right click', async () => {
        SURFACES[0].renderSurface()

        fireEvent(
            screen.getByText('Turn on session replay'),
            new MouseEvent('auxclick', { bubbles: true, cancelable: true, button: 2 })
        )

        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(intents).toEqual([])
    })

    it('leaves no unhandled rejection when recording the intent fails', async () => {
        intentStatus = 500
        SURFACES[0].renderSurface()

        fireEvent.click(screen.getByText('Turn on session replay'))

        await waitFor(() => expect(intents).toHaveLength(1))
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(unhandledRejections).toEqual([])
    })
})
