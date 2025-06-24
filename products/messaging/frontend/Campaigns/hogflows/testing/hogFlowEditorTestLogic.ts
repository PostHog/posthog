import { lemonToast } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
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
    PropertyGroupFilterValue,
} from '~/types'
import { PropertyGroupFilter } from '~/types'

import type { hogFlowEditorTestLogicType } from './hogFlowEditorTestLogicType'
import { HogFlow } from '../types'
import { CampaignLogicProps } from '../../campaignLogic'
import { campaignLogic } from '../../campaignLogic'

export interface HogFlowEditorTestLogicProps {
    id: HogFlow['id']
}

export interface HogflowTestInvocation {
    globals: string
    mock_async_functions: boolean
}

export interface HogflowTestResult {
    status: 'success' | 'error' | 'skipped'
    result?: any
    logs?: Array<{
        timestamp: string
        level: string
        message: string
    }>
}

export const hogFlowEditorTestLogic = kea<hogFlowEditorTestLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'hogflows', 'actions', 'workflowTestLogic']),
    props({} as HogFlowEditorTestLogicProps),
    key((props) => `${props.id}`),
    connect((props: CampaignLogicProps) => ({
        values: [campaignLogic(props), ['campaign']],
    })),
    actions({
        setTestResult: (testResult: HogflowTestResult | null) => ({ testResult }),
        toggleExpanded: true,
        setTestResultMode: (mode: 'raw' | 'diff') => ({ mode }),
        loadSampleGlobals: (payload?: { eventId?: string }) => ({ eventId: payload?.eventId }),
        setSampleGlobals: (sampleGlobals: CyclotronJobInvocationGlobals | null) => ({ sampleGlobals }),
        setSampleGlobalsError: (error: string | null) => ({ error }),
        cancelSampleGlobalsLoading: true,
        receiveExampleGlobals: (globals: object | null) => ({ globals }),
    }),
    reducers({
        expanded: [
            false,
            {
                toggleExpanded: (state) => !state,
            },
        ],
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
        sampleGlobals: [
            null as CyclotronJobInvocationGlobals | null,
            {
                setSampleGlobals: (_, { sampleGlobals }) => sampleGlobals,
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
                toggleExpanded: () => false,
            },
        ],
    }),
    selectors(({ values }) => ({
        canLoadSampleGlobals: [
            () => [],
            () => {
                return (
                    !!values.campaign.trigger?.filters?.events?.length ||
                    !!values.campaign.trigger?.filters?.actions?.length ||
                    !!values.campaign.trigger?.filters?.data_warehouse?.length
                )
            },
        ],
        // TODO(messaging): DRY up matchingFilters with implementation in hogFunctionConfigurationLogic
        matchingFilters: [
            () => [],
            (): PropertyGroupFilter => {
                const seriesProperties: PropertyGroupFilterValue = {
                    type: FilterLogicalOperator.Or,
                    values: [],
                }
                const properties: PropertyGroupFilter = {
                    type: FilterLogicalOperator.And,
                    values: [seriesProperties],
                }
                const allPossibleEventFilters = values.campaign.trigger.filters?.events ?? []
                const allPossibleActionFilters = values.campaign.trigger.filters?.actions ?? []

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
                if ((values.campaign.trigger.filters?.properties?.length ?? 0) > 0) {
                    const globalProperties: PropertyGroupFilterValue = {
                        type: FilterLogicalOperator.And,
                        values: [],
                    }
                    for (const property of values.campaign.trigger.filters?.properties ?? []) {
                        globalProperties.values.push(property as AnyPropertyFilter)
                    }
                    properties.values.push(globalProperties)
                }
                return properties
            },
            { resultEqualityCheck: equal },
        ],
    })),
    loaders(({ actions, values }) => ({
        testInvocation: [
            {
                globals: JSON.stringify(
                    {
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
                    },
                    null,
                    2
                ),
                mock_async_functions: true,
            } as HogflowTestInvocation,
            {
                submitTestInvocation: async () => {
                    try {
                        const apiResponse = await api.hogFlows.test(values.campaign.id, {
                            configuration: {},
                            globals: JSON.parse(values.testInvocation.globals),
                            mock_async_functions: values.testInvocation.mock_async_functions,
                        })

                        // Use the actual API response
                        const response: HogflowTestResult = {
                            status: apiResponse.status === 'error' ? 'error' : 'success',
                            result: apiResponse,
                            logs: [
                                {
                                    timestamp: new Date().toISOString(),
                                    level: apiResponse.status === 'error' ? 'error' : 'info',
                                    message:
                                        apiResponse.status === 'error'
                                            ? 'Workflow test failed'
                                            : 'Workflow test completed successfully',
                                },
                            ],
                        }
                        actions.setTestResult(response)
                        return values.testInvocation
                    } catch (error: any) {
                        console.error('Workflow test error:', error)
                        lemonToast.error('Error testing workflow')
                        throw error
                    }
                },
            },
        ],
        sampleGlobals: [
            null as CyclotronJobInvocationGlobals | null,
            {
                loadSampleGlobals: async () => {
                    if (!values.campaign.trigger?.filters) {
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
    forms(() => ({
        testInvocation: {
            defaults: {} as HogflowTestInvocation,
            errors: (data: HogflowTestInvocation) => {
                const errors: Record<string, string> = {}
                try {
                    JSON.parse(JSON.stringify(data.globals))
                } catch {
                    errors.globals = 'Invalid JSON'
                }
                return errors
            },
        },
    })),
    listeners(({ values, actions }) => ({
        loadSampleGlobalsSuccess: () => {
            if (values.expanded && !values.fetchCancelled && values.sampleGlobals) {
                actions.receiveExampleGlobals(values.sampleGlobals)
            }
        },
        setSampleGlobals: ({ sampleGlobals }) => {
            actions.receiveExampleGlobals(sampleGlobals)
        },
        receiveExampleGlobals: ({ globals }) => {
            if (!globals) {
                return
            }
            actions.setTestInvocationValue('globals', JSON.stringify(globals, null, 2))
        },
        cancelSampleGlobalsLoading: () => {
            // Just mark as cancelled - we'll ignore any results that come back
        },
    })),
])
