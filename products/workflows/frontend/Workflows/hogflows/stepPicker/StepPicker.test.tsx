import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType, UserType } from '~/types'

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

const stepTitleElement = (title: string): HTMLElement => {
    const titleElement = Array.from(
        stepColumn().querySelectorAll<HTMLElement>('[data-attr="workflow-step-picker-step-title"]')
    ).find((element) => element.textContent === title)
    expect(titleElement).toBeTruthy()
    return titleElement as HTMLElement
}

const rowTitled = (title: string): HTMLElement => stepTitleElement(title).closest('li') as HTMLElement

const visibleRowTitles = (): string[] =>
    within(stepColumn())
        .queryAllByRole('listitem')
        .map((row) => row.querySelector('[data-attr="workflow-step-picker-step-title"]')?.textContent)
        .filter((title): title is string => !!title)

const breadcrumb = (): HTMLElement => screen.getByLabelText('Breadcrumb')

const stepDetails = (): HTMLElement => screen.getByLabelText('Step details')

const OTHER_TEAM: TeamType = { ...MOCK_DEFAULT_TEAM, id: 4242, project_id: 4242 }
const OTHER_USER: UserType = { ...MOCK_DEFAULT_USER, uuid: 'another-user-uuid' }

const startKea = ({
    team = MOCK_DEFAULT_TEAM,
    user = MOCK_DEFAULT_USER,
    flags = ALL_STEP_FLAGS,
}: { team?: TeamType; user?: UserType; flags?: string[] } = {}): void => {
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        current_user: user,
    } as typeof window.POSTHOG_APP_CONTEXT
    initKeaTests(true, team)
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
}

describe('StepPicker', () => {
    let onPick: jest.Mock
    let unmount: () => void

    const renderPicker = (): void => {
        unmount = render(<StepPicker surface="tree" isRowScopedTrigger={false} onPick={onPick} />).unmount
    }

    beforeEach(() => {
        useMocks({ get: { [TEMPLATES_PATH]: { count: DESTINATION_TEMPLATES.length, results: DESTINATION_TEMPLATES } } })
        localStorage.clear()
        startKea()
        jest.clearAllMocks()
        onPick = jest.fn()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
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

        fireEvent.click(stepTitleElement('Send event'))
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
    it('goes back to All steps from the search breadcrumb without tracking the abandoned search', async () => {
        renderPicker()
        await waitFor(() => expect(screen.getByText('HubSpot')).toBeInTheDocument())
        jest.useFakeTimers()

        fireEvent.click(screen.getByText('Flow control'))
        fireEvent.change(screen.getByPlaceholderText('Search steps'), { target: { value: 'hub' } })
        fireEvent.click(within(breadcrumb()).getByText('All steps'))
        await jest.advanceTimersByTimeAsync(1000)

        expect(screen.getByText('Third party, A to Z')).toBeInTheDocument()
        expect(captured('workflow step picker searched')).toEqual([])
    })

    it('waits for integrations before saying a third-party favorite is missing', async () => {
        renderPicker()
        fireEvent.change(screen.getByPlaceholderText('Search steps'), { target: { value: 'hub' } })
        fireEvent.click(await waitFor(() => stepTitleElement('Create contact')))
        fireEvent.click(within(stepDetails()).getByText('Add to favorites'))
        unmount()

        let respondWithTemplates: () => void = () => {}
        const templatesResponse = new Promise<void>((resolve) => {
            respondWithTemplates = resolve
        })
        useMocks({
            get: {
                [TEMPLATES_PATH]: async () => {
                    await templatesResponse
                    return { count: DESTINATION_TEMPLATES.length, results: DESTINATION_TEMPLATES }
                },
            },
        })
        startKea()
        renderPicker()
        fireEvent.click(screen.getByText('Favorites'))

        expect(screen.queryByText('No favorites yet. Star a step to keep it here.')).not.toBeInTheDocument()

        respondWithTemplates()
        await waitFor(() => expect(visibleRowTitles()).toEqual(['Create contact']))
    })

    it('keeps starred steps under Favorites until they are unstarred', async () => {
        renderPicker()

        fireEvent.click(screen.getByText('Favorites'))
        expect(await screen.findByText('No favorites yet. Star a step to keep it here.')).toBeInTheDocument()

        fireEvent.click(screen.getByText('Highlights'))
        fireEvent.click(await waitFor(() => stepTitleElement('Slack')))
        fireEvent.click(within(stepDetails()).getByText('Add to favorites'))
        fireEvent.click(stepTitleElement('Run scout'))
        fireEvent.click(within(stepDetails()).getByText('Add to favorites'))

        fireEvent.click(screen.getByText('Favorites'))
        expect(visibleRowTitles()).toEqual(['Slack', 'Run scout'])

        fireEvent.click(stepTitleElement('Slack'))
        fireEvent.click(within(stepDetails()).getByText('Remove from favorites'))

        expect(visibleRowTitles()).toEqual(['Run scout'])
        expect(captured('workflow step picker favorite toggled')).toEqual([
            { surface: 'tree', step_id: 'template-slack', favorite: true },
            { surface: 'tree', step_id: 'template-posthog-run-scout', favorite: true },
            { surface: 'tree', step_id: 'template-slack', favorite: false },
        ])
    })

    it('lists the last five picked steps newest first under Recently used', async () => {
        renderPicker()

        fireEvent.click(screen.getByText('Recently used'))
        expect(await screen.findByText('Steps you add show up here.')).toBeInTheDocument()

        fireEvent.click(screen.getByText('Highlights'))
        const picks = ['Create AI task', 'Classify with AI', 'Run scout', 'Send message', 'Create task', 'Email']
        for (const title of [...picks, 'Classify with AI']) {
            fireEvent.click(within(await waitFor(() => rowTitled(title))).getByLabelText('Add step'))
        }

        fireEvent.click(screen.getByText('Recently used'))
        expect(visibleRowTitles()).toEqual(['Classify with AI', 'Email', 'Create task', 'Send message', 'Run scout'])
    })

    it('keeps favorites and recents per team and user, and only shows steps available here', async () => {
        renderPicker()
        fireEvent.click(screen.getByText('Highlights'))
        for (const title of ['Create AI task', 'Slack']) {
            fireEvent.click(await waitFor(() => stepTitleElement(title)))
            fireEvent.click(within(stepDetails()).getByText('Add to favorites'))
            fireEvent.click(within(rowTitled(title)).getByLabelText('Add step'))
        }
        unmount()

        const favoritesAndRecents = async (): Promise<string[][]> => {
            renderPicker()
            await waitFor(() => expect(screen.getByText('HubSpot')).toBeInTheDocument())
            fireEvent.click(screen.getByText('Favorites'))
            const favorites = visibleRowTitles()
            fireEvent.click(screen.getByText('Recently used'))
            const recents = visibleRowTitles()
            unmount()
            return [favorites, recents]
        }

        startKea()
        expect(await favoritesAndRecents()).toEqual([
            ['Create AI task', 'Slack'],
            ['Slack', 'Create AI task'],
        ])

        startKea({ team: OTHER_TEAM })
        expect(await favoritesAndRecents()).toEqual([[], []])

        startKea({ user: OTHER_USER })
        expect(await favoritesAndRecents()).toEqual([[], []])

        startKea({ flags: ALL_STEP_FLAGS.filter((flag) => flag !== FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION) })
        expect(await favoritesAndRecents()).toEqual([['Slack'], ['Slack']])
    })
})
