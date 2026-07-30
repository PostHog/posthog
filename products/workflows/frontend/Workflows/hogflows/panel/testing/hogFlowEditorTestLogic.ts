import { deepEqual as equal } from 'fast-equals'
import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { uuid } from 'lib/utils/dom'
import { performWideEventsQueryInTwoPhases } from 'scenes/hog-functions/sampleEventsQuery'

import { groupsModel } from '~/models/groupsModel'
import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { escapePropertyAsHogQLIdentifier, hogql } from '~/queries/utils'
import {
    AnyPropertyFilter,
    CyclotronJobInvocationGlobals,
    FilterLogicalOperator,
    GroupType,
    GroupTypeIndex,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
} from '~/types'

import { WorkflowLogicProps, workflowLogic } from '../../../workflowLogic'
import type { TriggerAction } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogflowTestResult } from '../../steps/types'
import type { HogFlow } from '../../types'

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
): CyclotronJobInvocationGlobals => {
    const resolvedTeamId = teamId || 1
    const projectUrl = `${window.location.origin}/project/${resolvedTeamId}`
    const eventUuid = uuid()
    const eventTimestamp = dayjs().toISOString()
    return {
        event: {
            uuid: eventUuid,
            distinct_id: uuid(),
            timestamp: eventTimestamp,
            elements_chain: '',
            url: `${projectUrl}/events/${encodeURIComponent(eventUuid)}/${encodeURIComponent(eventTimestamp)}`,
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
            id: resolvedTeamId,
            name: 'Default project',
            url: projectUrl,
        },
        source: {
            name: workflowName ?? 'Unnamed',
            url: window.location.href.split('#')[0],
        },
    }
}

// HogQL tuple columns appended to the events query so we can resolve each group type's
// key + properties for the sample, mirroring real execution which resolves them from $groups.
export const groupSelectColumns = (groupTypes: Map<GroupTypeIndex, GroupType>): string[] => {
    const columns: string[] = []
    groupTypes.forEach((groupType) => {
        const name = escapePropertyAsHogQLIdentifier(groupType.group_type)
        columns.push(`tuple(${name}.created_at, ${name}.index, ${name}.key, ${name}.properties, ${name}.updated_at)`)
    })
    return columns
}

// Parse the group tuples appended by groupSelectColumns (offsets start after event + person).
export const parseGroupsFromResult = (
    result: any[],
    groupTypes: Map<GroupTypeIndex, GroupType>
): NonNullable<CyclotronJobInvocationGlobals['groups']> => {
    const groups: NonNullable<CyclotronJobInvocationGlobals['groups']> = {}
    // Use a positional counter, not the Map key: groupSelectColumns appends columns in iteration
    // order, so column n sits at result[2 + n] regardless of each type's group_type_index.
    let position = 0
    groupTypes.forEach((groupType) => {
        const tuple = result?.[2 + position++]
        if (tuple && Array.isArray(tuple) && tuple[2]) {
            let properties = {}
            try {
                properties = JSON.parse(tuple[3])
            } catch {
                // Ignore malformed properties
            }
            groups[groupType.group_type] = {
                type: groupType.group_type,
                index: tuple[1],
                id: tuple[2],
                url: `${window.location.origin}/groups/${tuple[1]}/${encodeURIComponent(tuple[2])}`,
                properties,
            }
        }
    })
    return groups
}

export const createGlobalsFromResponse = (
    event: any,
    person: any,
    teamId: number,
    workflowName?: string | null,
    groups: CyclotronJobInvocationGlobals['groups'] = {}
): CyclotronJobInvocationGlobals => {
    const projectUrl = `${window.location.origin}/project/${teamId}`
    return {
        event: {
            uuid: event.uuid,
            distinct_id: event.distinct_id,
            timestamp: event.timestamp,
            elements_chain: event.elements_chain || '',
            url:
                event.url ||
                `${projectUrl}/events/${encodeURIComponent(event.uuid)}/${encodeURIComponent(event.timestamp)}`,
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
        groups,
        project: {
            id: teamId,
            name: 'Default project',
            url: projectUrl,
        },
        source: {
            name: workflowName ?? 'Unnamed',
            url: window.location.href.split('#')[0],
        },
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogFlowEditorTestLogicValues {
    groupsEnabled: boolean // groupsAccessLogic
    groupTypes: Map<GroupTypeIndex, GroupType> // groupsModel
    selectedNodeId: string | null // hogFlowEditorLogic
    triggerAction: TriggerAction | null // workflowLogic
    workflow: HogFlow // workflowLogic
    workflowSanitized: HogFlow // workflowLogic
    accumulatedVariables: Record<string, any>
    canTryExtendedSearch: boolean
    eventPanelOpen: string[]
    eventSelectorOpen: boolean
    fetchCancelled: boolean
    groupTypesForTest: Map<GroupTypeIndex, GroupType>
    isTestInvocationSubmitting: boolean
    isTestInvocationValid: boolean
    lastSearchedEventName: string | null
    matchingFilters: PropertyGroupFilter
    nextActionId: string | null
    noMatchingEvents: boolean
    sampleGlobals: CyclotronJobInvocationGlobals | null
    sampleGlobalsError: string | null
    sampleGlobalsLoading: boolean
    shouldLoadSampleGlobals: boolean
    showTestInvocationErrors: boolean
    testInvocation: HogflowTestInvocation
    testInvocationAllErrors: Record<string, any>
    testInvocationChanged: boolean
    testInvocationErrors: DeepPartialMap<HogflowTestInvocation, ValidationErrorType>
    testInvocationHasErrors: boolean
    testInvocationManualErrors: Record<string, any>
    testInvocationTouched: boolean
    testInvocationTouches: Record<string, boolean>
    testInvocationValidationErrors: DeepPartialMap<HogflowTestInvocation, ValidationErrorType>
    testResult: HogflowTestResult | null
    testResultMode: 'diff' | 'raw'
    workflowVariableDefaults: Record<string, any>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogFlowEditorTestLogicActions {
    setAnimatingEdgePair: (
        from: string,
        to: string
    ) => {
        from: string
        to: string
    } // hogFlowEditorLogic
    setSelectedNodeId: (selectedNodeId: string | null) => {
        selectedNodeId: string | null
    } // hogFlowEditorLogic
    cancelSampleGlobalsLoading: () => {
        value: true
    }
    loadSampleEventByName: (payload: { eventName: string; extendedSearch?: boolean }) => {
        eventName: string
        extendedSearch: boolean | undefined
    }
    loadSampleEventByNameFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSampleEventByNameSuccess: (
        sampleGlobals: CyclotronJobInvocationGlobals | null,
        payload?: {
            eventName: string
            extendedSearch: boolean | undefined
        }
    ) => {
        sampleGlobals: CyclotronJobInvocationGlobals | null
        payload?: {
            eventName: string
            extendedSearch: boolean | undefined
        }
    }
    loadSampleGlobals: (payload?: { eventId?: string; extendedSearch?: boolean }) => {
        eventId: string | undefined
        extendedSearch: boolean | undefined
    }
    loadSampleGlobalsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSampleGlobalsSuccess: (
        sampleGlobals: CyclotronJobInvocationGlobals | null,
        payload?: {
            eventId: string | undefined
            extendedSearch: boolean | undefined
        }
    ) => {
        sampleGlobals: CyclotronJobInvocationGlobals | null
        payload?: {
            eventId: string | undefined
            extendedSearch: boolean | undefined
        }
    }
    receiveExampleGlobals: (globals: object | null) => {
        globals: object | null
    }
    resetAccumulatedVariables: () => {
        value: true
    }
    resetTestInvocation: (values?: HogflowTestInvocation) => {
        values?: HogflowTestInvocation
    }
    setCanTryExtendedSearch: (canTryExtendedSearch: boolean) => {
        canTryExtendedSearch: boolean
    }
    setEventPanelOpen: (eventPanelOpen: string[]) => {
        eventPanelOpen: string[]
    }
    setEventSelectorOpen: (eventSelectorOpen: boolean) => {
        eventSelectorOpen: boolean
    }
    setLastSearchedEventName: (eventName: string | null) => {
        eventName: string | null
    }
    setNextActionId: (nextActionId: string | null) => {
        nextActionId: string | null
    }
    setNoMatchingEvents: (noMatchingEvents: boolean) => {
        noMatchingEvents: boolean
    }
    setSampleGlobals: (globals?: string | null) => {
        globals: string | null | undefined
    }
    setSampleGlobalsError: (error: string | null) => {
        error: string | null
    }
    setTestInvocationManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setTestInvocationValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setTestInvocationValues: (values: DeepPartial<HogflowTestInvocation>) => {
        values: DeepPartial<HogflowTestInvocation>
    }
    setTestResult: (testResult: HogflowTestResult | null) => {
        testResult: HogflowTestResult | null
    }
    setTestResultMode: (mode: 'diff' | 'raw') => {
        mode: 'diff' | 'raw'
    }
    submitTestInvocation: () => {
        value: boolean
    }
    submitTestInvocationFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitTestInvocationRequest: (testInvocation: HogflowTestInvocation) => {
        testInvocation: HogflowTestInvocation
    }
    submitTestInvocationSuccess: (testInvocation: HogflowTestInvocation) => {
        testInvocation: HogflowTestInvocation
    }
    touchTestInvocationField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogFlowEditorTestLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        shouldLoadSampleGlobals: (
            triggerAction:
                | ({
                      config:
                          | {
                                type: 'schedule'
                            }
                          | {
                                filters: {
                                    properties: any[]
                                }
                                type: 'batch'
                            }
                          | {
                                filters: {
                                    actions?: any[] | undefined
                                    events?: any[] | undefined
                                    filter_test_accounts?: boolean | undefined
                                    properties?: any[] | undefined
                                }
                                type: 'event'
                            }
                          | {
                                filters: {
                                    properties?: any[] | undefined
                                }
                                key_property?: string | undefined
                                table_name: string
                                type: 'data-warehouse-table'
                            }
                          | {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                template_id: string
                                template_uuid?: string | undefined
                                type: 'manual'
                            }
                          | {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                template_id: string
                                template_uuid?: string | undefined
                                type: 'tracking_pixel'
                            }
                          | {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                template_id: string
                                template_uuid?: string | undefined
                                type: 'webhook'
                            }
                      created_at?: number | undefined
                      description: string
                      filters?:
                          | {
                                actions?: any[] | undefined
                                events?: any[] | undefined
                                properties?: any[] | undefined
                            }
                          | null
                          | undefined
                      id: string
                      name: string
                      on_error?: 'abort' | 'continue' | null | undefined
                      output_variable?:
                          | {
                                key: string
                                label?: string | null | undefined
                                result_path?: string | null | undefined
                                spread?: boolean | null | undefined
                            }
                          | {
                                key: string
                                label?: string | null | undefined
                                result_path?: string | null | undefined
                                spread?: boolean | null | undefined
                            }[]
                          | null
                          | undefined
                      type: 'trigger'
                      updated_at?: number | undefined
                  } & Record<string, unknown>)
                | null
        ) => boolean
        groupTypesForTest: (
            groupsEnabled: boolean,
            groupTypes: Map<GroupTypeIndex, GroupType>
        ) => Map<GroupTypeIndex, GroupType>
        matchingFilters: (
            triggerAction:
                | ({
                      config:
                          | {
                                type: 'schedule'
                            }
                          | {
                                filters: {
                                    properties: any[]
                                }
                                type: 'batch'
                            }
                          | {
                                filters: {
                                    actions?: any[] | undefined
                                    events?: any[] | undefined
                                    filter_test_accounts?: boolean | undefined
                                    properties?: any[] | undefined
                                }
                                type: 'event'
                            }
                          | {
                                filters: {
                                    properties?: any[] | undefined
                                }
                                key_property?: string | undefined
                                table_name: string
                                type: 'data-warehouse-table'
                            }
                          | {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                template_id: string
                                template_uuid?: string | undefined
                                type: 'manual'
                            }
                          | {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                template_id: string
                                template_uuid?: string | undefined
                                type: 'tracking_pixel'
                            }
                          | {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                template_id: string
                                template_uuid?: string | undefined
                                type: 'webhook'
                            }
                      created_at?: number | undefined
                      description: string
                      filters?:
                          | {
                                actions?: any[] | undefined
                                events?: any[] | undefined
                                properties?: any[] | undefined
                            }
                          | null
                          | undefined
                      id: string
                      name: string
                      on_error?: 'abort' | 'continue' | null | undefined
                      output_variable?:
                          | {
                                key: string
                                label?: string | null | undefined
                                result_path?: string | null | undefined
                                spread?: boolean | null | undefined
                            }
                          | {
                                key: string
                                label?: string | null | undefined
                                result_path?: string | null | undefined
                                spread?: boolean | null | undefined
                            }[]
                          | null
                          | undefined
                      type: 'trigger'
                      updated_at?: number | undefined
                  } & Record<string, unknown>)
                | null
        ) => PropertyGroupFilter
        workflowVariableDefaults: (workflow: HogFlow) => Record<string, any>
    }
}

export type hogFlowEditorTestLogicType = MakeLogicType<
    hogFlowEditorTestLogicValues,
    hogFlowEditorTestLogicActions,
    WorkflowLogicProps,
    hogFlowEditorTestLogicMeta
>

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
            groupsModel,
            ['groupTypes'],
            groupsAccessLogic,
            ['groupsEnabled'],
        ],
        actions: [hogFlowEditorLogic, ['setSelectedNodeId', 'setAnimatingEdgePair']],
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
                            select: ['*', 'person', ...groupSelectColumns(values.groupTypesForTest)],
                            after: timeRange,
                            limit: 10,
                            orderBy: ['timestamp DESC'],
                            modifiers: {
                                // NOTE: We always want to show events with the person properties at the time the event was created as that is what the function will see
                                personsOnEventsMode: 'person_id_no_override_properties_on_events',
                            },
                        }

                        const response = await performWideEventsQueryInTwoPhases(query)

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
                        const groups = parseGroupsFromResult(response.results[resultIndex], values.groupTypesForTest)

                        return createGlobalsFromResponse(
                            event,
                            person,
                            values.workflow.team_id,
                            values.workflow.name,
                            groups
                        )
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
                            select: ['*', 'person', ...groupSelectColumns(values.groupTypesForTest)],
                            after: timeRange,
                            limit: 1,
                            orderBy: ['timestamp DESC'],
                            modifiers: {
                                personsOnEventsMode: 'person_id_no_override_properties_on_events',
                            },
                        }

                        const response = await performWideEventsQueryInTwoPhases(query)

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
                        const groups = parseGroupsFromResult(response.results[0], values.groupTypesForTest)

                        actions.setSampleGlobalsError(null)
                        actions.setCanTryExtendedSearch(false)
                        return createGlobalsFromResponse(
                            event,
                            person,
                            values.workflow.team_id,
                            values.workflow.name,
                            groups
                        )
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
            (triggerAction: null | import('../../../workflowLogic').TriggerAction): boolean => {
                // Only load samples if the trigger is event
                return !!(triggerAction && triggerAction.config.type === 'event')
            },
        ],
        // Mirror real execution: the worker's getGroupsForEvent gates on group_analytics, so without
        // the addon the test run must also resolve no groups (otherwise a group condition could match
        // here but never in production).
        groupTypesForTest: [
            (s) => [s.groupsEnabled, s.groupTypes],
            (groupsEnabled: boolean, groupTypes: Map<GroupTypeIndex, GroupType>): Map<GroupTypeIndex, GroupType> =>
                groupsEnabled ? groupTypes : new Map(),
        ],
        // TODO(workflows): DRY up matchingFilters with implementation in hogFunctionConfigurationLogic
        matchingFilters: [
            (s) => [s.triggerAction],
            (triggerAction: null | import('../../../workflowLogic').TriggerAction): PropertyGroupFilter => {
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
            (workflow: import('../../types').HogFlow): Record<string, any> =>
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
        setTestResult: ({ testResult }) => {
            if (testResult?.nextActionId && values.selectedNodeId) {
                actions.setAnimatingEdgePair(values.selectedNodeId, testResult.nextActionId)
            }
        },
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
