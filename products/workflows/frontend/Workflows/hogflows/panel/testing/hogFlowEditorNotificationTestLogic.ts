import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'

import { performQuery } from '~/queries/query'
import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { CyclotronJobInvocationGlobals, FilterLogicalOperator, PersonType, PropertyFilterType } from '~/types'

import { WorkflowLogicProps, workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogflowTestResult } from '../../steps/types'
import type { hogFlowEditorNotificationTestLogicType } from './hogFlowEditorNotificationTestLogicType'
import { createExampleEvent, createGlobalsFromResponse } from './hogFlowEditorTestLogic'
import type { HogflowTestInvocation } from './hogFlowEditorTestLogic'

// Time range constants for event search
const STANDARD_SEARCH_RANGE = `-7d`

export const hogFlowEditorNotificationTestLogic = kea<hogFlowEditorNotificationTestLogicType>([
    path((key) => [
        'products',
        'workflows',
        'frontend',
        'Workflows',
        'hogflows',
        'panel',
        'testing',
        'hogFlowEditorNotificationTestLogic',
        key,
    ]),
    props({} as WorkflowLogicProps),
    key((props) => `${props.id}`),
    connect((props: WorkflowLogicProps) => ({
        values: [workflowLogic(props), ['workflow', 'workflowSanitized'], hogFlowEditorLogic, ['selectedNodeId']],
        actions: [hogFlowEditorLogic, ['setSelectedNodeId']],
    })),
    actions({
        setPersonSelectorOpen: (open: boolean) => ({ open }),
        setPersonSearchTerm: (term: string) => ({ term }),
        loadSamplePersons: true,
        searchPersons: (searchTerm: string) => ({ searchTerm }),
        clearPersonSearch: true,
        loadSamplePersonByDistinctId: (payload: { distinctId: string }) => ({
            distinctId: payload.distinctId,
        }),
        loadSamplePersonByDistinctIdSuccess: (sampleGlobals: CyclotronJobInvocationGlobals | null) => ({
            sampleGlobals,
        }),
        loadSamplePersonByDistinctIdFailure: (error: string, errorObject?: any) => ({ error, errorObject }),
        setEmailAddressOverride: (email: string) => ({ email }),
        setSampleGlobals: (globals?: string | null) => ({ globals: globals ?? null }),
        setSampleGlobalsError: (error: string | null) => ({ error }),
        setTestResult: (testResult: HogflowTestResult | null) => ({ testResult }),
        setNextActionId: (nextActionId: string | null) => ({ nextActionId }),
    }),
    reducers({
        personSelectorOpen: [
            false as boolean,
            {
                setPersonSelectorOpen: (_, { open }) => open,
                loadSamplePersonByDistinctIdSuccess: () => false,
            },
        ],
        personSearchTerm: [
            '' as string,
            {
                setPersonSearchTerm: (_, { term }) => term,
                clearPersonSearch: () => '',
            },
        ],
        emailAddressOverride: [
            null as string | null,
            {
                setEmailAddressOverride: (_, { email }) => email,
                loadSamplePersonByDistinctIdSuccess: (_, { sampleGlobals }) => {
                    // Update email override when person changes
                    return sampleGlobals?.person?.properties?.email ?? null
                },
            },
        ],
        testResult: [
            null as HogflowTestResult | null,
            {
                setTestResult: (_, { testResult }) => testResult,
            },
        ],
        nextActionId: [
            null as string | null,
            {
                setNextActionId: (_, { nextActionId }) => nextActionId,
            },
        ],
        sampleGlobals: [
            null as CyclotronJobInvocationGlobals | null,
            {
                setSampleGlobals: (previousGlobals, { globals }) => {
                    try {
                        return globals ? JSON.parse(globals) : previousGlobals
                    } catch {
                        return previousGlobals
                    }
                },
                loadSamplePersonByDistinctIdSuccess: (_, { sampleGlobals }) => sampleGlobals,
            },
        ],
        sampleGlobalsLoading: [
            false as boolean,
            {
                loadSamplePersonByDistinctId: () => true,
                loadSamplePersonByDistinctIdSuccess: () => false,
                loadSamplePersonByDistinctIdFailure: () => false,
            },
        ],
        sampleGlobalsError: [
            null as string | null,
            {
                setSampleGlobalsError: (_, { error }) => error,
                loadSamplePersonByDistinctIdSuccess: () => null,
            },
        ],
    }),
    loaders(() => ({
        samplePersons: [
            [] as PersonType[],
            {
                loadSamplePersons: async () => {
                    const response = await api.persons.list({ limit: 5 })
                    if (!response.results || response.results.length === 0) {
                        return []
                    }
                    return response.results
                },
            },
        ],
        personSearchResults: [
            [] as PersonType[],
            {
                searchPersons: async ({ searchTerm }) => {
                    if (!searchTerm.trim()) {
                        return []
                    }
                    try {
                        const response = await api.persons.list({ search: searchTerm.trim(), limit: 10 })
                        return response.results
                    } catch (error) {
                        console.error('Failed to search persons:', error)
                        return []
                    }
                },
            },
        ],
    })),
    forms(({ actions, values }) => ({
        testInvocation: {
            defaults: {
                mock_async_functions: false,
            } as HogflowTestInvocation,
            errors: (data: HogflowTestInvocation) => {
                const errors: Record<string, string> = {}
                try {
                    JSON.parse(data.globals)
                } catch {
                    errors.globals = 'Invalid JSON'
                }
                return errors
            },
            submit: async (testInvocation: HogflowTestInvocation) => {
                try {
                    const parsedGlobals = JSON.parse(testInvocation.globals)

                    // Override email in person properties if emailAddressOverride is set
                    if (values.emailAddressOverride && parsedGlobals.person) {
                        parsedGlobals.person = {
                            ...parsedGlobals.person,
                            properties: {
                                ...parsedGlobals.person.properties,
                                email: values.emailAddressOverride,
                            },
                        }
                    }

                    const apiResponse = await api.hogFlows.createTestInvocation(values.workflow.id, {
                        configuration: values.workflowSanitized,
                        globals: {
                            ...parsedGlobals,
                            variables: values.workflow.variables?.reduce(
                                (acc, variable) => {
                                    acc[variable.key] = variable.default
                                    return acc
                                },
                                {} as Record<string, any>
                            ),
                        },
                        mock_async_functions: testInvocation.mock_async_functions,
                        current_action_id: values.selectedNodeId ?? undefined,
                    })

                    const result: HogflowTestResult = {
                        ...apiResponse,
                        logs: apiResponse.logs?.map((log) => ({
                            ...log,
                            instanceId: 'test',
                            timestamp: dayjs(log.timestamp),
                        })),
                    }

                    actions.setTestResult(result)
                    const nextActionId = result.nextActionId
                    if (nextActionId && nextActionId !== values.selectedNodeId) {
                        actions.setNextActionId(nextActionId)
                    }

                    return values.testInvocation
                } catch (error: any) {
                    console.error('Workflow test error:', error)
                    lemonToast.error('Error testing workflow')
                    throw error
                }
            },
        },
    })),
    listeners(({ actions, values }) => ({
        loadSamplePersonByDistinctId: async ({ distinctId }) => {
            try {
                // First, get the person by distinct_id
                const personResponse = await api.persons.list({ distinct_id: distinctId, limit: 1 })
                if (!personResponse?.results?.[0]) {
                    actions.setSampleGlobalsError(`No person found with distinct_id: ${distinctId}`)
                    actions.loadSamplePersonByDistinctIdFailure('Failed to load person')
                    return
                }

                const person = personResponse.results[0]

                // Find the most recent event for this person
                const query: EventsQuery = {
                    kind: NodeKind.EventsQuery,
                    fixedProperties: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: PropertyFilterType.HogQL,
                                    key: hogql`distinct_id = ${distinctId}`,
                                },
                            ],
                        },
                    ],
                    select: ['*', 'person'],
                    after: STANDARD_SEARCH_RANGE,
                    limit: 1,
                    orderBy: ['timestamp DESC'],
                    modifiers: {
                        personsOnEventsMode: 'person_id_no_override_properties_on_events',
                    },
                }

                const eventResponse = await performQuery(query)
                let event = eventResponse?.results?.[0]?.[0]

                if (!event) {
                    // If no event found, create a minimal example event
                    event = {
                        uuid: uuid(),
                        distinct_id: distinctId,
                        timestamp: dayjs().toISOString(),
                        elements_chain: '',
                        url: `${window.location.origin}/project/${values.workflow.team_id}/events/`,
                        event: '$pageview',
                        properties: {
                            $current_url: window.location.href.split('#')[0],
                        },
                    }
                }

                actions.setSampleGlobalsError(null)
                const globals = createGlobalsFromResponse(event, person, values.workflow.team_id, values.workflow.name)
                actions.loadSamplePersonByDistinctIdSuccess(globals)
            } catch (error: any) {
                actions.setSampleGlobalsError(`Failed to load person: ${error.message || 'Unknown error'}`)
                actions.loadSamplePersonByDistinctIdFailure('Failed to load person')
            }
        },
        setPersonSearchTerm: async ({ term }, breakpoint) => {
            // Debounce search - wait 300ms before searching
            await breakpoint(300)

            if (term === values.personSearchTerm && term.trim()) {
                actions.searchPersons(term)
            } else if (!term.trim()) {
                actions.searchPersons('')
            }
        },
        setPersonSelectorOpen: ({ open }) => {
            if (open && values.samplePersons.length === 0) {
                actions.loadSamplePersons()
            }
        },
        loadSamplePersonsSuccess: ({ samplePersons }) => {
            if (samplePersons.length > 0 && !values.sampleGlobals) {
                const firstPerson = samplePersons[0]
                const distinctId = firstPerson.distinct_ids?.[0]
                if (distinctId) {
                    actions.loadSamplePersonByDistinctId({ distinctId })
                }
            }
        },
        loadSamplePersonsFailure: () => {
            // Only create example person if loading fails
            if (!values.sampleGlobals) {
                const exampleGlobals = createExampleEvent(
                    values.workflow.team_id,
                    values.workflow.name,
                    '$pageview',
                    ''
                )
                actions.setSampleGlobals(JSON.stringify(exampleGlobals, null, 2))
            }
        },
        setSampleGlobals: () => {
            if (values.sampleGlobals) {
                actions.setTestInvocationValue('globals', JSON.stringify(values.sampleGlobals, null, 2))
            }
        },
        loadSamplePersonByDistinctIdSuccess: ({ sampleGlobals }) => {
            // Reorder with person first before setting
            if (sampleGlobals) {
                const reorderedGlobals = reorderGlobalsForEmailAction(sampleGlobals)
                actions.setSampleGlobals(JSON.stringify(reorderedGlobals, null, 2))
            }

            if (sampleGlobals?.person?.properties?.email) {
                actions.setEmailAddressOverride(sampleGlobals.person.properties.email)
            }
        },
    })),
    afterMount(({ actions }) => {
        // Load sample persons on mount
        actions.loadSamplePersons()
    }),
])

export function reorderGlobalsForEmailAction(globals: CyclotronJobInvocationGlobals): CyclotronJobInvocationGlobals {
    // Reorder globals to show person before event for email actions,
    // because that's where we expect users to want to make changes
    return Object.fromEntries(
        Object.entries(globals).sort(([keyA], [keyB]) => {
            const order: Record<string, number> = {
                person: 0,
                event: 1,
            }
            const orderA = order[keyA] ?? 2
            const orderB = order[keyB] ?? 2
            if (orderA !== orderB) {
                return orderA - orderB
            }
            return keyA.localeCompare(keyB)
        })
    ) as CyclotronJobInvocationGlobals
}
