import { actions, connect, defaults, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { ErrorEventProperties, ErrorEventType } from 'lib/components/Errors/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import {
    DateRange,
    ErrorTrackingIssue,
    ErrorTrackingIssueAggregations,
    ErrorTrackingRelationalIssue,
} from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb, IntegrationType } from '~/types'

import { errorFiltersLogic } from './components/ErrorFilters/errorFiltersLogic'
import { issueActionsLogic } from './components/IssueActions/issueActionsLogic'
import type { errorTrackingIssueSceneLogicType } from './errorTrackingIssueSceneLogicType'
import { errorTrackingIssueQuery } from './queries'
import { ERROR_TRACKING_DETAILS_RESOLUTION } from './utils'
import { subscriptions } from 'kea-subscriptions'

export interface ErrorTrackingIssueSceneLogicProps {
    id: ErrorTrackingIssue['id']
    fingerprint?: string
    timestamp?: string
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
        loadInitialEvent: (timestamp: string) => ({ timestamp }),
        setInitialEventTimestamp: (timestamp: string | null) => ({ timestamp }),
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
        initialEvent: null as ErrorEventType | null,
        selectedEvent: null as ErrorEventType | null,
        initialEventTimestamp: null as string | null,
        initialEventLoading: true as boolean,
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
        initialEventTimestamp: {
            setInitialEventTimestamp: (state, { timestamp }) => {
                if (!state && timestamp) {
                    return timestamp
                }
                return state
            },
        },
        selectedEvent: {
            selectEvent: (_, { event }) => {
                if (!event && values.initialEvent) {
                    return values.initialEvent
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
        initialEvent: {
            loadInitialEvent: async ({ timestamp }) => {
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId: props.id,
                        dateRange: getNarrowDateRange(timestamp),
                        filterTestAccounts: false,
                        withAggregations: false,
                        withFirstEvent: false,
                        withLastEvent: true,
                    }),
                    { refresh: 'blocking' }
                )
                const issue = response.results[0]
                let positionEvent = null
                if (issue.last_event) {
                    positionEvent = issue.last_event
                } else {
                    return null
                }
                const initialEvent: ErrorEventType = {
                    uuid: positionEvent.uuid,
                    timestamp: positionEvent.timestamp,
                    person: { distinct_ids: [], properties: {} },
                    properties: JSON.parse(positionEvent.properties),
                }
                if (!values.selectedEvent) {
                    actions.selectEvent(initialEvent)
                }
                return initialEvent
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
                        withLastEvent: false,
                    }),
                    { refresh: 'blocking' }
                )
                if (!response.results.length) {
                    return null
                }
                if (response.results[0] && response.results[0].last_seen) {
                    actions.setLastSeen(dayjs(response.results[0].last_seen))
                    actions.setInitialEventTimestamp(response.results[0].last_seen)
                }
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

    subscriptions(({ actions }) => ({
        initialEventTimestamp: (value: string | null, oldValue: string | null) => {
            if (!oldValue && value) {
                actions.loadInitialEvent(value)
            }
        },
    })),

    listeners(({ actions }) => {
        return {
            setDateRange: actions.loadSummary,
            setFilterGroup: actions.loadSummary,
            setFilterTestAccounts: actions.loadSummary,
            setSearchQuery: actions.loadSummary,
            loadIssueFailure: ({ errorObject: { status, data } }) => {
                if (status == 308 && 'issue_id' in data) {
                    router.actions.replace(urls.errorTrackingIssue(data.issue_id))
                }
            },
            selectEvent: ({ event }) => {
                if (event) {
                    router.actions.replace(
                        router.values.currentLocation.pathname,
                        {
                            ...router.values.searchParams,
                            timestamp: event.timestamp,
                        },
                        router.values.hashParams
                    )
                }
            },
        }
    }),

    events(({ props, actions }) => ({
        afterMount: () => {
            actions.loadIssue()
            actions.setInitialEventTimestamp(props.timestamp ?? null)
            actions.loadSummary()
        },
    })),
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
