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

import { CampaignLogicProps, campaignLogic } from '../../../campaignLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { HogflowTestResult } from '../../steps/types'
import type { hogFlowEditorTestLogicType } from './hogFlowEditorTestLogicType'

export interface HogflowTestInvocation {
    globals: string
    mock_async_functions: boolean
}

export const hogFlowEditorTestLogic = kea<hogFlowEditorTestLogicType>([
    path((key) => ['products', 'messaging', 'frontend', 'Campaigns', 'hogflows', 'actions', 'workflowTestLogic', key]),
    props({} as CampaignLogicProps),
    key((props) => `${props.id}`),
    connect((props: CampaignLogicProps) => ({
        values: [
            campaignLogic(props),
            ['campaign', 'campaignSanitized', 'triggerAction'],
            hogFlowEditorLogic,
            ['selectedNodeId'],
        ],
        actions: [hogFlowEditorLogic, ['setSelectedNodeId']],
    })),
    actions({
        setTestResult: (testResult: HogflowTestResult | null) => ({ testResult }),
        setTestResultMode: (mode: 'raw' | 'diff') => ({ mode }),
        loadSampleGlobals: (payload?: { eventId?: string }) => ({ eventId: payload?.eventId }),
        setSampleGlobals: (globals?: string | null) => ({ globals }),
        setSampleGlobalsError: (error: string | null) => ({ error }),
        cancelSampleGlobalsLoading: true,
        receiveExampleGlobals: (globals: object | null) => ({ globals }),
        setNextActionId: (nextActionId: string | null) => ({ nextActionId }),
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
    }),

    loaders(({ actions, values }) => ({
        sampleGlobals: [
            null as CyclotronJobInvocationGlobals | null,
            {
                loadSampleGlobals: async () => {
                    if (!values.shouldLoadSampleGlobals) {
                        return null
                    }

                    const errorMessage =
                        'No events match these filters in the last 30 days. Showing an example $pageview event instead.'

                    try {
                        const query: EventsQuery = {
                            kind: NodeKind.EventsQuery,
                            fixedProperties: [values.matchingFilters],
                            select: ['*', 'person'],
                            after: '-7d',
                            limit: 1,
                            orderBy: ['timestamp DESC'],
                            modifiers: {
                                // NOTE: We always want to show events with the person properties at the time the event was created as that is what the function will see
                                personsOnEventsMode: 'person_id_no_override_properties_on_events',
                            },
                        }

                        const response = await performQuery(query)

                        if (!response?.results?.[0]) {
                            throw new Error(errorMessage)
                        }

                        const event = response.results[0][0]
                        const person = response.results[0][1]

                        const globals = {
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
                                id: values.campaign.team_id,
                                name: 'Default project',
                                url: `${window.location.origin}/project/${values.campaign.team_id}`,
                            },
                            source: {
                                name: values.campaign.name ?? 'Unnamed',
                                url: window.location.href.split('#')[0],
                            },
                        }

                        return globals
                    } catch (e: any) {
                        if (!e.message?.includes('breakpoint')) {
                            actions.setSampleGlobalsError(e.message ?? errorMessage)
                        }
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
        // TODO(messaging): DRY up matchingFilters with implementation in hogFunctionConfigurationLogic
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
                    const apiResponse = await api.hogFlows.createTestInvocation(values.campaign.id, {
                        configuration: values.campaignSanitized,
                        globals: JSON.parse(testInvocation.globals),
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
    })),

    afterMount(({ actions, values }) => {
        actions.loadSampleGlobalsSuccess({
            event: {
                uuid: uuid(),
                distinct_id: uuid(),
                timestamp: dayjs().toISOString(),
                elements_chain: '',
                url: `${window.location.origin}/project/1/events/`,
                event: '$pageview',
                properties: {
                    $current_url: window.location.href.split('#')[0],
                    $browser: 'Chrome',
                    this_is_an_example_event: true,
                },
            },
            person: {
                id: uuid(),
                properties: {
                    email: 'example@posthog.com',
                },
                name: 'Example person',
                url: `${window.location.origin}/person/${uuid()}`,
            },
            groups: {},
            project: {
                id: 1,
                name: 'Default project',
                url: `${window.location.origin}/project/1`,
            },
            source: {
                name: values.campaign.name ?? 'Unnamed',
                url: window.location.href.split('#')[0],
            },
        })
    }),
])
