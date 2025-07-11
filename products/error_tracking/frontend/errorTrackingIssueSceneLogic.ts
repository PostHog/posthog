import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { ErrorEventProperties, ErrorEventType } from 'lib/components/Errors/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { Params, Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import {
    DateRange,
    ErrorTrackingIssue,
    ErrorTrackingIssueAggregations,
    ErrorTrackingRelationalIssue,
} from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb, IntegrationType } from '~/types'

import {
    ERROR_TRACKING_DEFAULT_DATE_RANGE,
    ERROR_TRACKING_DEFAULT_FILTER_GROUP,
    ERROR_TRACKING_DEFAULT_SEARCH_QUERY,
    ERROR_TRACKING_DEFAULT_TEST_ACCOUNT,
    errorFiltersLogic,
} from './components/ErrorFilters/errorFiltersLogic'
import { issueActionsLogic } from './components/IssueActions/issueActionsLogic'
import type { errorTrackingIssueSceneLogicType } from './errorTrackingIssueSceneLogicType'
import { errorTrackingIssueQuery } from './queries'
import { ERROR_TRACKING_DETAILS_RESOLUTION, syncSearchParams, updateSearchParams } from './utils'
import equal from 'fast-deep-equal'

export interface ErrorTrackingIssueSceneLogicProps {
    id: ErrorTrackingIssue['id']
    fingerprint?: string
}

export type ErrorTrackingIssueStatus = ErrorTrackingIssue['status']

export const errorTrackingIssueSceneLogic = kea<errorTrackingIssueSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingIssueSceneLogic', key]),
    props({} as ErrorTrackingIssueSceneLogicProps),
    key((props) => props.id),

    connect(() => {
        const filtersLogic = errorFiltersLogic()
        const issueActions = issueActionsLogic()
        return {
            values: [filtersLogic, ['dateRange', 'filterTestAccounts', 'filterGroup', 'searchQuery']],
            actions: [
                filtersLogic,
                ['setDateRange', 'setFilterTestAccounts', 'setFilterGroup', 'setSearchQuery'],
                issueActions,
                ['updateIssueAssignee', 'updateIssueStatus', 'updateIssueName'],
            ],
        }
    }),

    actions({
        loadIssue: true,
        loadSummary: true,
        loadFirstSeenEvent: (timestamp: string) => ({ timestamp }),
        setIssue: (issue: ErrorTrackingRelationalIssue) => ({ issue }),
        setLastSeen: (lastSeen: Dayjs) => ({ lastSeen }),
        selectEvent: (event: ErrorEventType | null) => ({
            event,
        }),
        createExternalReference: (integrationId: IntegrationType['id'], config: Record<string, string>) => ({
            integrationId,
            config,
        }),
    }),

    defaults({
        issue: null as ErrorTrackingRelationalIssue | null,
        summary: null as ErrorTrackingIssueSummary | null,
        properties: null as ErrorEventProperties | null,
        lastSeen: null as Dayjs | null,
        firstSeenEvent: null as ErrorEventType | null,
        selectedEvent: null as ErrorEventType | null,
    }),

    reducers(({ values }) => ({
        issue: {
            setIssue: (_, { issue }: { issue: ErrorTrackingRelationalIssue }) => issue,
            updateIssueAssignee: (state, { id, assignee }) => {
                if (state && id == state.id) {
                    return { ...state, assignee }
                }
                return state
            },
            updateIssueStatus: (state, { id, status }) => {
                if (state && id == state.id) {
                    return { ...state, status }
                }
                return state
            },
            updateIssueName: (state, { name }) => {
                return state ? { ...state, name } : null
            },
        },
        summary: {},
        lastSeen: {
            setLastSeen: (prevLastSeen, { lastSeen }) => {
                if (!prevLastSeen || prevLastSeen.isBefore(lastSeen)) {
                    return lastSeen
                }
                return prevLastSeen
            },
        },
        selectedEvent: {
            selectEvent: (_, { event }) => {
                if (!event && values.firstSeenEvent) {
                    return values.firstSeenEvent
                }
                return event
            },
        },
    })),

    loaders(({ values, actions, props }) => ({
        issue: {
            loadIssue: async () => await api.errorTracking.getIssue(props.id, props.fingerprint),
            createExternalReference: async ({ integrationId, config }) => {
                if (values.issue) {
                    const response = await api.errorTracking.createExternalReference(props.id, integrationId, config)
                    // TODO: we only allow one external reference until we redesign the page
                    return { ...values.issue, external_issues: [response] }
                }
                return null
            },
        },
        firstSeenEvent: {
            loadFirstSeenEvent: async ({ timestamp }) => {
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId: props.id,
                        dateRange: getNarrowDateRange(timestamp),
                        filterTestAccounts: false,
                        withAggregations: false,
                        withFirstEvent: true,
                    }),
                    { refresh: 'blocking' }
                )
                const issue = response.results[0]
                if (!issue.first_event) {
                    return null
                }
                const first_event_properties = JSON.parse(issue.first_event.properties)
                const firstSeenEvent: ErrorEventType = {
                    uuid: issue.first_event.uuid,
                    timestamp: issue.first_event.timestamp,
                    person: { distinct_ids: [], properties: {} },
                    properties: first_event_properties,
                }
                if (!values.selectedEvent) {
                    actions.selectEvent(firstSeenEvent)
                }
                return firstSeenEvent
            },
        },
        summary: {
            loadSummary: async () => {
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId: props.id,
                        dateRange: values.dateRange,
                        filterTestAccounts: values.filterTestAccounts,
                        filterGroup: values.filterGroup,
                        searchQuery: values.searchQuery,
                        volumeResolution: ERROR_TRACKING_DETAILS_RESOLUTION,
                        withAggregations: true,
                        withFirstEvent: false,
                    }),
                    { refresh: 'blocking' }
                )
                if (!response.results.length) {
                    return null
                }
                actions.setLastSeen(dayjs(response.results[0].last_seen))
                const summary = response.results[0]
                if (!summary.aggregations) {
                    return null
                }
                return {
                    aggregations: summary.aggregations,
                }
            },
        },
    })),

    selectors(({ actions, props }) => ({
        breadcrumbs: [
            (s) => [s.issue],
            (issue: ErrorTrackingRelationalIssue | null): Breadcrumb[] => {
                const exceptionType: string = issue?.name || 'Issue'
                return [
                    {
                        key: Scene.ErrorTracking,
                        name: 'Error tracking',
                        path: urls.errorTracking(),
                    },
                    {
                        key: [Scene.ErrorTrackingIssue, exceptionType],
                        name: exceptionType,
                        onRename: async (name: string) => {
                            return actions.updateIssueName(props.id, name)
                        },
                    },
                ]
            },
        ],

        [SIDE_PANEL_CONTEXT_KEY]: [
            (_, p) => [p.id],
            (issueId): SidePanelSceneContext => {
                return {
                    activity_scope: ActivityScope.ERROR_TRACKING_ISSUE,
                    activity_item_id: issueId,
                }
            },
        ],
        issueId: [(_, p) => [p.id], (id: string) => id],
        firstSeen: [
            (s) => [s.issue],
            (issue: ErrorTrackingRelationalIssue | null) => (issue ? dayjs(issue.first_seen) : null),
        ],

        aggregations: [(s) => [s.summary], (summary: ErrorTrackingIssueSummary | null) => summary?.aggregations],
    })),

    listeners(({ actions }) => {
        return {
            setDateRange: actions.loadSummary,
            setFilterGroup: actions.loadSummary,
            setFilterTestAccounts: actions.loadSummary,
            setSearchQuery: actions.loadSummary,
            loadIssue: actions.loadSummary,
            loadIssueSuccess: [({ issue }) => actions.loadFirstSeenEvent(issue.first_seen)],
            loadIssueFailure: ({ errorObject: { status, data } }) => {
                if (status == 308 && 'issue_id' in data) {
                    router.actions.replace(urls.errorTrackingIssue(data.issue_id))
                }
            },
        }
    }),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, { dateRange, filterGroup, filterTestAccounts, searchQuery }: Params): void => {
            const hasParams = !!dateRange || !!filterGroup || !!filterTestAccounts || !!searchQuery

            if (dateRange && !equal(dateRange, values.dateRange)) {
                actions.setDateRange(dateRange)
            } else if (hasParams && !dateRange) {
                actions.setDateRange(ERROR_TRACKING_DEFAULT_DATE_RANGE)
            }
            if (filterGroup && !equal(filterGroup, values.filterGroup)) {
                actions.setFilterGroup(filterGroup)
            } else if (hasParams && !filterGroup) {
                actions.setFilterGroup(ERROR_TRACKING_DEFAULT_FILTER_GROUP)
            }
            if (filterTestAccounts && !equal(filterTestAccounts, values.filterTestAccounts)) {
                actions.setFilterTestAccounts(filterTestAccounts)
            } else if (hasParams && !filterTestAccounts) {
                actions.setFilterTestAccounts(ERROR_TRACKING_DEFAULT_TEST_ACCOUNT)
            }
            if (searchQuery && !equal(searchQuery, values.searchQuery)) {
                actions.setSearchQuery(searchQuery)
            } else if (hasParams && !searchQuery) {
                actions.setSearchQuery(ERROR_TRACKING_DEFAULT_SEARCH_QUERY)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    actionToUrl(({ values }) => {
        const buildURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            }
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(
                    params,
                    'filterTestAccounts',
                    values.filterTestAccounts,
                    ERROR_TRACKING_DEFAULT_TEST_ACCOUNT
                )
                updateSearchParams(params, 'searchQuery', values.searchQuery, ERROR_TRACKING_DEFAULT_SEARCH_QUERY)
                updateSearchParams(params, 'filterGroup', values.filterGroup, ERROR_TRACKING_DEFAULT_FILTER_GROUP)
                updateSearchParams(params, 'dateRange', values.dateRange, ERROR_TRACKING_DEFAULT_DATE_RANGE)
                return params
            })
        }

        return {
            setDateRange: () => buildURL(),
            setFilterGroup: () => buildURL(),
            setSearchQuery: () => buildURL(),
            setFilterTestAccounts: () => buildURL(),
        }
    }),
])

function getNarrowDateRange(timestamp: Dayjs | string): DateRange {
    const firstSeen = dayjs(timestamp)
    return {
        date_from: firstSeen.subtract(1, 'hour').toISOString(),
        date_to: firstSeen.add(1, 'hour').toISOString(),
    }
}

export type ErrorTrackingIssueSummary = {
    aggregations: ErrorTrackingIssueAggregations
}
