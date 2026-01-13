import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'

import { performQuery } from '~/queries/query'
import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import {
    AnyPropertyFilter,
    CyclotronJobInvocationGlobals,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
} from '~/types'

import { WorkflowLogicProps, workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogflowTestResult } from '../../steps/types'
import type { hogFlowEditorTestLogicType } from './hogFlowEditorTestLogicType'

// Time range constants for event search
const STANDARD_SEARCH_DAYS = 7
const EXTENDED_SEARCH_DAYS = 30
const STANDARD_SEARCH_RANGE = `-${STANDARD_SEARCH_DAYS}d`
const EXTENDED_SEARCH_RANGE = `-${EXTENDED_SEARCH_DAYS}d`

export interface HogflowTestInvocation {
    globals: string
    mock_async_functions: boolean
}

export const createExampleEvent = (
    teamId?: number,
    workflowName?: string | null,
    eventName: string = '$pageview',
    email: string = 'example@posthog.com'
): CyclotronJobInvocationGlobals => ({
    event: {
        uuid: uuid(),
        distinct_id: uuid(),
        timestamp: dayjs().toISOString(),
        elements_chain: '',
        url: `${window.location.origin}/project/${teamId || 1}/events/`,
        event: eventName,
        properties: {
            $current_url: window.location.href.split('#')[0],
            $browser: 'Chrome',
            this_is_an_example_event: true,
        },
    },
    person: {
        id: uuid(),
        properties: {
            email,
        },
        name: 'Example person',
        url: `${window.location.origin}/person/${uuid()}`,
    },
    groups: {},
    project: {
        id: teamId || 1,
        name: 'Default project',
        url: `${window.location.origin}/project/${teamId || 1}`,
    },
    source: {
        name: workflowName ?? 'Unnamed',
        url: window.location.href.split('#')[0],
    },
})

export const createGlobalsFromResponse = (
    event: any,
    person: any,
    teamId: number,
    workflowName?: string | null
): CyclotronJobInvocationGlobals => ({
    event: {
        uuid: event.uuid,
        distinct_id: event.distinct_id,
        timestamp: event.timestamp,
        elements_chain: event.elements_chain || '',
        url: event.url || '',
        event: event.event,
        properties: event.properties,
    },
    person: person
        ? {
              id: person.id,
              properties: person.properties,
              name: person.name || 'Unknown person',
              url: `${window.location.origin}/person/${person.id}`,
          }
        : undefined,
    groups: {},
    project: {
        id: teamId,
        name: 'Default project',
        url: `${window.location.origin}/project/${teamId}`,
    },
    source: {
        name: workflowName ?? 'Unnamed',
        url: window.location.href.split('#')[0],
    },
})

export const hogFlowEditorTestLogic = kea<hogFlowEditorTestLogicType>([
    path((key) => ['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'actions', 'workflowTestLogic', key]),
    props({} as WorkflowLogicProps),
    key((props) => `${props.id}`),
    connect((props: WorkflowLogicProps) => ({
        values: [
            workflowLogic(props),
            ['workflow', 'workflowSanitized', 'triggerAction'],
            hogFlowEditorLogic,
            ['selectedNodeId'],
        ],
        actions: [hogFlowEditorLogic, ['setSelectedNodeId']],
    })),
    actions({
        setTestResult: (testResult: HogflowTestResult | null) => ({ testResult }),
        setTestResultMode: (mode: 'raw' | 'diff') => ({ mode }),
        loadSampleGlobals: (payload?: { eventId?: string; extendedSearch?: boolean }) => ({
            eventId: payload?.eventId,
            extendedSearch: payload?.extendedSearch,
        }),
        loadSampleEventByName: (payload: { eventName: string; extendedSearch?: boolean }) => ({
            eventName: payload.eventName,
            extendedSearch: payload.extendedSearch,
        }),
        setSampleGlobals: (globals?: string | null) => ({ globals }),
        setSampleGlobalsError: (error: string | null) => ({ error }),
        setNoMatchingEvents: (noMatchingEvents: boolean) => ({ noMatchingEvents }),
        setCanTryExtendedSearch: (canTryExtendedSearch: boolean) => ({ canTryExtendedSearch }),
        cancelSampleGlobalsLoading: true,
        receiveExampleGlobals: (globals: object | null) => ({ globals }),
        setNextActionId: (nextActionId: string | null) => ({ nextActionId }),
        setEventPanelOpen: (eventPanelOpen: string[]) => ({ eventPanelOpen }),
        setEventSelectorOpen: (eventSelectorOpen: boolean) => ({ eventSelectorOpen }),
        setLastSearchedEventName: (eventName: string | null) => ({ eventName }),
        resetAccumulatedVariables: true,
    }),
    reducers({
        testResult: [
            null as HogflowTestResult | null,
            {
                setTestResult: (_, { testResult }) => testResult,
            },
        ],
        testResultMode: [
            'raw' as 'raw' | 'diff',
            {
                setTestResultMode: (_, { mode }) => mode,
            },
        ],
        sampleGlobalsError: [
            null as string | null,
            {
                loadSampleGlobals: () => null,
                setSampleGlobalsError: (_, { error }) => error,
            },
        ],
        noMatchingEvents: [
            false as boolean,
            {
                loadSampleGlobals: () => false,
                setNoMatchingEvents: (_, { noMatchingEvents }) => noMatchingEvents,
            },
        ],
        canTryExtendedSearch: [
            false as boolean,
            {
                loadSampleGlobals: () => false,
                setCanTryExtendedSearch: (_, { canTryExtendedSearch }) => canTryExtendedSearch,
            },
        ],
        fetchCancelled: [
            false as boolean,
            {
                loadSampleGlobals: () => false,
                cancelSampleGlobalsLoading: () => true,
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
            },
        ],
        eventPanelOpen: [
            ['event'] as string[],
            {
                setEventPanelOpen: (_, { eventPanelOpen }) => eventPanelOpen,
            },
        ],
        eventSelectorOpen: [
            false as boolean,
            {
                setEventSelectorOpen: (_, { eventSelectorOpen }) => eventSelectorOpen,
                loadSampleEventByNameSuccess: () => false, // Close selector after loading
            },
        ],
        lastSearchedEventName: [
            null as string | null,
            {
                setLastSearchedEventName: (_, { eventName }) => eventName,
                loadSampleEventByName: (_, { eventName }) => eventName, // Store the event name when searching
            },
        ],
        // Track variables accumulated from previous step tests
        accumulatedVariables: [
            {} as Record<string, any>,
            {
                setTestResult: (state, { testResult }) =>
                    testResult?.variables ? { ...state, ...testResult.variables } : state,
                resetAccumulatedVariables: () => ({}),
                // Reset when loading fresh sample globals (starting a new test session)
                loadSampleGlobals: () => ({}),
                loadSampleEventByName: () => ({}),
            },
        ],
    }),

    loaders(({ actions, values }) => ({
        sampleGlobals: [
            null as CyclotronJobInvocationGlobals | null,
            {
                loadSampleGlobals: async ({ extendedSearch }) => {
                    if (!values.shouldLoadSampleGlobals) {
                        return null
                    }

                    try {
                        // Use extended or standard search range
                        const timeRange = extendedSearch ? EXTENDED_SEARCH_RANGE : STANDARD_SEARCH_RANGE

                        // Fetch multiple events so we can cycle through them
                        const query: EventsQuery = {
                            kind: NodeKind.EventsQuery,
                            fixedProperties: [values.matchingFilters],
                            select: ['*', 'person'],
                            after: timeRange,
                            limit: 10,
                            orderBy: ['timestamp DESC'],
                            modifiers: {
                                // NOTE: We always want to show events with the person properties at the time the event was created as that is what the function will see
                                personsOnEventsMode: 'person_id_no_override_properties_on_events',
                            },
                        }

                        const response = await performQuery(query)

                        if (!response?.results?.[0]) {
                            // No matching events found
                            const exampleGlobals = createExampleEvent(values.workflow.team_id, values.workflow.name)
                            actions.setNoMatchingEvents(true)

                            if (extendedSearch) {
                                // Extended search also failed
                                actions.setSampleGlobalsError(
                                    `No events match these filters in the last ${EXTENDED_SEARCH_DAYS} days. Using an example $pageview event instead.`
                                )
                                actions.setCanTryExtendedSearch(false)
                            } else {
                                // First search failed, allow extended search
                                actions.setSampleGlobalsError(
                                    `No events match these filters in the last ${STANDARD_SEARCH_DAYS} days. Using an example $pageview event instead.`
                                )
                                actions.setCanTryExtendedSearch(true)
                            }

                            return exampleGlobals
                        }

                        // Found matching events
                        actions.setNoMatchingEvents(false)
                        actions.setCanTryExtendedSearch(false)

                        // Pick a different event than the current one if possible
                        let resultIndex = 0
                        if (values.sampleGlobals?.event?.uuid && response.results.length > 1) {
                            // Find the index of the current event
                            const currentIndex = response.results.findIndex(
                                (result) => result[0].uuid === values.sampleGlobals?.event?.uuid
                            )
                            // Pick the next event in the list, cycling back to the start if needed
                            if (currentIndex !== -1) {
                                resultIndex = (currentIndex + 1) % response.results.length
                            }
                        }

                        const event = response.results[resultIndex][0]
                        const person = response.results[resultIndex][1]

                        return createGlobalsFromResponse(event, person, values.workflow.team_id, values.workflow.name)
                    } catch (e: any) {
                        if (!e.message?.includes('breakpoint')) {
                            actions.setSampleGlobalsError('Failed to load matching events. Please try again.')
                        }
                        return null
                    }
                },
                loadSampleEventByName: async ({
                    eventName,
                    extendedSearch,
                }): Promise<CyclotronJobInvocationGlobals | null> => {
                    // Load a specific event by name (for non-event triggers)
                    try {
                        const timeRange = extendedSearch ? EXTENDED_SEARCH_RANGE : STANDARD_SEARCH_RANGE

                        const query: EventsQuery = {
                            kind: NodeKind.EventsQuery,
                            fixedProperties: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [
                                        {
                                            type: PropertyFilterType.HogQL,
                                            key: hogql`event = ${eventName}`,
                                        },
                                    ],
                                },
                            ],
                            select: ['*', 'person'],
                            after: timeRange,
                            limit: 1,
                            orderBy: ['timestamp DESC'],
                            modifiers: {
                                personsOnEventsMode: 'person_id_no_override_properties_on_events',
                            },
                        }

                        const response = await performQuery(query)

                        if (!response?.results?.[0]) {
                            // No matching events found, use standard example event
                            const exampleGlobals = createExampleEvent(values.workflow.team_id, values.workflow.name)

                            if (extendedSearch) {
                                // Extended search also failed
                                actions.setSampleGlobalsError(
                                    `No "${eventName}" events found in the last ${EXTENDED_SEARCH_DAYS} days. Using an example $pageview event instead.`
                                )
                                actions.setCanTryExtendedSearch(false)
                            } else {
                                // First search failed, allow extended search
                                actions.setSampleGlobalsError(
                                    `No "${eventName}" events found in the last ${STANDARD_SEARCH_DAYS} days. Using an example $pageview event instead.`
                                )
                                actions.setCanTryExtendedSearch(true)
                            }

                            return exampleGlobals
                        }

                        const event = response.results[0][0]
                        const person = response.results[0][1]

                        actions.setSampleGlobalsError(null)
                        actions.setCanTryExtendedSearch(false)
                        return createGlobalsFromResponse(event, person, values.workflow.team_id, values.workflow.name)
                    } catch {
                        actions.setSampleGlobalsError('Failed to load event. Please try again.')
                        return null
                    }
                },
            },
        ],
    })),
    selectors(() => ({
        shouldLoadSampleGlobals: [
            (s) => [s.triggerAction],
            (triggerAction): boolean => {
                // Only load samples if the trigger is event
                return !!(triggerAction && triggerAction.config.type === 'event')
            },
        ],
        // TODO(workflows): DRY up matchingFilters with implementation in hogFunctionConfigurationLogic
        matchingFilters: [
            (s) => [s.triggerAction],
            (triggerAction): PropertyGroupFilter => {
                if (!triggerAction || triggerAction.config.type !== 'event') {
                    return {
                        type: FilterLogicalOperator.And,
                        values: [],
                    }
                }

                const triggerActionConfig = triggerAction.config

                const seriesProperties: PropertyGroupFilterValue = {
                    type: FilterLogicalOperator.Or,
                    values: [],
                }
                const properties: PropertyGroupFilter = {
                    type: FilterLogicalOperator.And,
                    values: [seriesProperties],
                }
                const allPossibleEventFilters = triggerActionConfig.filters?.events ?? []
                const allPossibleActionFilters = triggerActionConfig.filters?.actions ?? []

                for (const event of allPossibleEventFilters) {
                    const eventProperties: AnyPropertyFilter[] = [...(event.properties ?? [])]
                    if (event.id) {
                        eventProperties.push({
                            type: PropertyFilterType.HogQL,
                            key: hogql`event = ${event.id}`,
                        })
                    }
                    if (eventProperties.length === 0) {
                        eventProperties.push({
                            type: PropertyFilterType.HogQL,
                            key: 'true',
                        })
                    }
                    seriesProperties.values.push({
                        type: FilterLogicalOperator.And,
                        values: eventProperties,
                    })
                }
                for (const action of allPossibleActionFilters) {
                    const actionProperties: AnyPropertyFilter[] = [...(action.properties ?? [])]
                    if (action.id) {
                        actionProperties.push({
                            type: PropertyFilterType.HogQL,
                            key: hogql`matchesAction(${parseInt(action.id)})`,
                        })
                    }
                    seriesProperties.values.push({
                        type: FilterLogicalOperator.And,
                        values: actionProperties,
                    })
                }
                if ((triggerActionConfig.filters?.properties?.length ?? 0) > 0) {
                    const globalProperties: PropertyGroupFilterValue = {
                        type: FilterLogicalOperator.And,
                        values: [],
                    }
                    for (const property of triggerActionConfig.filters?.properties ?? []) {
                        globalProperties.values.push(property as AnyPropertyFilter)
                    }
                    properties.values.push(globalProperties)
                }
                return properties
            },
            { resultEqualityCheck: equal },
        ],
        workflowVariableDefaults: [
            (s) => [s.workflow],
            (workflow): Record<string, any> =>
                workflow.variables?.reduce(
                    (acc, variable) => {
                        acc[variable.key] = variable.default
                        return acc
                    },
                    {} as Record<string, any>
                ) ?? {},
        ],
    })),
    forms(({ actions, values }) => ({
        testInvocation: {
            defaults: {
                mock_async_functions: true,
            } as HogflowTestInvocation,
            errors: (data: HogflowTestInvocation) => {
                const errors: Record<string, string> = {}
                try {
                    JSON.parse(JSON.stringify(data.globals))
                } catch {
                    errors.globals = 'Invalid JSON'
                }
                return errors
            },
            submit: async (testInvocation: HogflowTestInvocation) => {
                try {
                    const apiResponse = await api.hogFlows.createTestInvocation(values.workflow.id, {
                        configuration: values.workflowSanitized,
                        globals: {
                            ...JSON.parse(testInvocation.globals),
                            // Merge order: defaults < accumulated (variables set by previous test steps take precedence)
                            variables: {
                                ...values.workflowVariableDefaults,
                                ...values.accumulatedVariables,
                            },
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
    listeners(({ values, actions }) => ({
        loadSampleGlobalsSuccess: () => {
            actions.setTestInvocationValue('globals', JSON.stringify(values.sampleGlobals, null, 2))
        },
        setSampleGlobals: () => {
            actions.setTestInvocationValue('globals', JSON.stringify(values.sampleGlobals, null, 2))
        },
        cancelSampleGlobalsLoading: () => {
            // Just mark as cancelled - we'll ignore any results that come back
        },
        setSelectedNodeId: () => {
            // When we switch back to a trigger node, reset the flags
            // so we can try loading again
            if (values.noMatchingEvents) {
                actions.setNoMatchingEvents(false)
                actions.setCanTryExtendedSearch(false)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        // If we can load actual events (i.e., trigger is configured), load them automatically
        if (values.shouldLoadSampleGlobals) {
            actions.loadSampleGlobals()
        } else {
            // Only use example event if we can't load actual events
            const exampleGlobals = createExampleEvent(values.workflow.team_id, values.workflow.name)
            actions.loadSampleGlobalsSuccess(exampleGlobals)
        }
    }),
])
