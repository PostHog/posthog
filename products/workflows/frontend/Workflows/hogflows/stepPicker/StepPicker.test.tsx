import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DESTINATION_TEMPLATES } from './stepCatalogTestTemplates'
import { StepPicker } from './StepPicker'

jest.mock('posthog-js')

const ALL_STEP_FLAGS = [
    FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION,
    FEATURE_FLAGS.WORKFLOW_RUN_SCOUT_ACTION,
    FEATURE_FLAGS.WORKFLOW_CLASSIFY_ACTION,
    FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS,
]

const TEMPLATES_PATH = '/api/projects/:team_id/hog_function_templates'

const captures = (): [string, Record<string, any>][] => (posthog.capture as jest.Mock).mock.calls as any
const captured = (event: string): Record<string, any>[] =>
    captures()
        .filter(([name]) => name === event)
        .map(([, properties]) => properties)

const stepColumn = (): HTMLElement => screen.getByLabelText('Steps')

const rowTitled = (title: string): HTMLElement => {
    const row = within(stepColumn()).getByText(title).closest('li')
    expect(row).not.toBeNull()
    return row as HTMLElement
}

const visibleRowTitles = (): string[] =>
    within(stepColumn())
        .getAllByRole('listitem')
        .map((row) => row.querySelector('[data-attr="workflow-step-picker-step-title"]')?.textContent)
        .filter((title): title is string => !!title)

const breadcrumb = (): HTMLElement => screen.getByLabelText('Breadcrumb')

describe('StepPicker', () => {
    let onPick: jest.Mock
    let unmount: () => void

    const renderPicker = (): void => {
        unmount = render(<StepPicker surface="tree" isRowScopedTrigger={false} onPick={onPick} />).unmount
    }

    beforeEach(() => {
        useMocks({ get: { [TEMPLATES_PATH]: { count: DESTINATION_TEMPLATES.length, results: DESTINATION_TEMPLATES } } })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(
            ALL_STEP_FLAGS,
            Object.fromEntries(ALL_STEP_FLAGS.map((flag) => [flag, true]))
        )
        jest.clearAllMocks()
        onPick = jest.fn()
    })

    afterEach(() => {
        cleanup()
    })

    it('finds a vendor step by vendor name and adds it from the row', async () => {
        renderPicker()
        expect(captured('workflow step picker opened')).toEqual([{ surface: 'tree' }])

        fireEvent.change(screen.getByPlaceholderText('Search steps'), { target: { value: 'hub' } })

        for (const operation of ['Create contact', 'Create company', 'Send event']) {
            expect(within(await waitFor(() => rowTitled(operation))).getByText('HubSpot')).toBeInTheDocument()
        }
        expect(within(breadcrumb()).getByText('Search')).toBeInTheDocument()

        fireEvent.click(within(rowTitled('Create contact')).getByLabelText('Add step'))

        expect(onPick).toHaveBeenCalledWith({
            type: 'function',
            name: 'Hubspot',
            description: 'Hubspot destination',
            config: { template_id: 'template-hubspot', inputs: {} },
        })
        expect(captured('workflow step picker step picked')).toEqual([
            {
                surface: 'tree',
                step_id: 'template-hubspot',
                origin: 'third_party',
                product: null,
                vendor: 'HubSpot',
                category: 'crm',
                view: 'all',
                from_search: true,
                via: 'row',
            },
        ])
        await waitFor(
            () =>
                expect(captured('workflow step picker searched')).toEqual([
                    { surface: 'tree', query: 'hub', result_count: expect.any(Number) },
                ]),
            { timeout: 2500 }
        )

        unmount()
        expect(captured('workflow step picker closed')).toEqual([{ surface: 'tree', picked: true }])
    })

    it('lists PostHog products first, then vendors A to Z, and opens a vendor folder', async () => {
        renderPicker()

        const providerLabels = (): string[] =>
            Array.from(document.querySelectorAll('[data-attr="workflow-step-picker-provider"]')).map(
                (provider) =>
                    provider.querySelector('[data-attr="workflow-step-picker-provider-label"]')?.textContent ?? ''
            )
        await waitFor(() => expect(providerLabels()).toContain('HubSpot'))
        expect(providerLabels().slice(0, 6)).toEqual([
            'Workflows',
            'PostHog',
            'Support',
            'Customer analytics',
            'Tasks',
            'Signals',
        ])
        expect(visibleRowTitles().slice(0, 3)).toEqual(['ActiveCampaign', 'Airtable', 'AWS Kinesis'])

        fireEvent.click(screen.getByText('HubSpot'))

        expect(captured('workflow step picker provider opened')).toEqual([
            { surface: 'tree', provider: 'vendor:HubSpot' },
        ])
        expect(within(breadcrumb()).getByText('All steps')).toBeInTheDocument()
        expect(within(breadcrumb()).getByText('HubSpot')).toBeInTheDocument()
        expect(visibleRowTitles()).toEqual(['Create contact', 'Create company', 'Send event'])

        fireEvent.click(within(rowTitled('Send event')).getByText('Send event'))
        fireEvent.click(within(screen.getByLabelText('Step details')).getByText('Add step'))

        expect(onPick).toHaveBeenCalledWith(
            expect.objectContaining({ config: { template_id: 'template-hubspot-event', inputs: {} } })
        )
        expect(captured('workflow step picker step picked')).toEqual([
            expect.objectContaining({ step_id: 'template-hubspot-event', from_search: false, via: 'detail' }),
        ])
    })

    it('shows the curated highlights in order', async () => {
        renderPicker()

        fireEvent.click(screen.getByText('Highlights'))

        expect(captured('workflow step picker view changed')).toEqual([{ surface: 'tree', view: 'highlights' }])
        await waitFor(() =>
            expect(visibleRowTitles()).toEqual([
                'Create AI task',
                'Classify with AI',
                'Run scout',
                'Send message',
                'Create task',
                'Email',
                'Slack',
                'Conditional branch',
            ])
        )
    })

    it('keeps built-in steps listed when integrations fail to load', async () => {
        useMocks({ get: { [TEMPLATES_PATH]: () => [500, { detail: 'boom' }] } })
        renderPicker()

        expect(
            await screen.findByText("Couldn't load integrations. Built-in steps are still listed.")
        ).toBeInTheDocument()
        expect(screen.getByText('Workflows')).toBeInTheDocument()

        useMocks({ get: { [TEMPLATES_PATH]: { count: DESTINATION_TEMPLATES.length, results: DESTINATION_TEMPLATES } } })
        fireEvent.click(screen.getAllByText('Retry')[0])

        expect(await screen.findByText('HubSpot')).toBeInTheDocument()
        expect(
            screen.queryByText("Couldn't load integrations. Built-in steps are still listed.")
        ).not.toBeInTheDocument()
    })

    it('offers a way back when a search matches nothing', async () => {
        renderPicker()
        await waitFor(() => expect(screen.getByText('HubSpot')).toBeInTheDocument())

        fireEvent.change(screen.getByPlaceholderText('Search steps'), { target: { value: 'qqqzzz' } })
        expect(screen.getByText('No steps match "qqqzzz".')).toBeInTheDocument()

        fireEvent.click(screen.getByText('Clear search'))
        expect(screen.getByPlaceholderText('Search steps')).toHaveValue('')
        expect(screen.getByText('HubSpot')).toBeInTheDocument()
    })
})
