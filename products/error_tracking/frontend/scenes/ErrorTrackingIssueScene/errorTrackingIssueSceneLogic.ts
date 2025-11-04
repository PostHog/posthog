import { actions, connect, defaults, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { ErrorEventProperties, ErrorEventType, ErrorTrackingFingerprint } from 'lib/components/Errors/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import {
    DateRange,
    ErrorTrackingIssue,
    ErrorTrackingIssueAggregations,
    ErrorTrackingRelationalIssue,
    SimilarIssue,
} from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb, IntegrationType } from '~/types'

import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import { errorTrackingIssueEventsQuery, errorTrackingIssueQuery, errorTrackingSimilarIssuesQuery } from '../../queries'
import { ERROR_TRACKING_DETAILS_RESOLUTION } from '../../utils'
import type { errorTrackingIssueSceneLogicType } from './errorTrackingIssueSceneLogicType'

export interface ErrorTrackingIssueSceneLogicProps {
    id: ErrorTrackingIssue['id']
    fingerprint?: string
    timestamp?: string
}

export type ErrorTrackingIssueStatus = ErrorTrackingIssue['status']

export const ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY = 'ErrorTrackingIssueScene'

export const errorTrackingIssueSceneLogic = kea<errorTrackingIssueSceneLogicType>([
    path((key) => [
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingIssueScene',
        'errorTrackingIssueSceneLogic',
        key,
    ]),
    props({} as ErrorTrackingIssueSceneLogicProps),
    key((props) => props.id),

    connect(() => ({
        values: [
            issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }),
            ['dateRange', 'filterTestAccounts', 'filterGroup', 'searchQuery'],
        ],
        actions: [
            issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }),
            ['setDateRange', 'setFilterTestAccounts', 'setFilterGroup', 'setSearchQuery'],
            issueActionsLogic,
            ['updateIssueAssignee', 'updateIssueStatus', 'updateIssueName', 'updateIssueDescription'],
        ],
    })),

    actions({
        loadIssue: true,
        loadSummary: true,
        loadInitialEvent: (timestamp: string) => ({ timestamp }),
        setInitialEventTimestamp: (timestamp: string | null) => ({ timestamp }),
        setIssue: (issue: ErrorTrackingRelationalIssue) => ({ issue }),
        setLastSeen: (lastSeen: string) => ({ lastSeen }),
        selectEvent: (event: ErrorEventType | null) => ({
            event,
        }),
        createExternalReference: (integrationId: IntegrationType['id'], config: Record<string, string>) => ({
            integrationId,
            config,
        }),
        updateAssignee: (assignee: ErrorTrackingIssue['assignee']) => ({ assignee }),
        updateStatus: (status: ErrorTrackingIssue['status']) => ({ status }),
        updateName: (name: string) => ({ name }),
        updateDescription: (description: string) => ({ description }),
        setSimilarIssuesMaxDistance: (distance: number) => ({ distance }),
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
        similarIssuesMaxDistance: 0.2 as number,
    }),

    reducers(({ values }) => ({
        summary: {},
        lastSeen: {
            setLastSeen: (prevLastSeen, { lastSeen }) => {
                const lastSeenDayjs = dayjs(lastSeen)
                if (!prevLastSeen || prevLastSeen.isBefore(lastSeenDayjs)) {
                    return lastSeenDayjs
                }
                return prevLastSeen
            },
        },
        similarIssuesMaxDistance: {
            setSimilarIssuesMaxDistance: (_, { distance }) => distance,
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
            setIssue: ({ issue }) => issue,
            loadIssue: async () => await api.errorTracking.getIssue(props.id, props.fingerprint),
            createExternalReference: async ({ integrationId, config }) => {
                if (values.issue) {
                    const response = await api.errorTracking.createExternalReference(props.id, integrationId, config)
                    const externalIssues = values.issue.external_issues ?? []
                    return { ...values.issue, external_issues: [...externalIssues, response] }
                }
                return null
            },
            updateAssignee: ({ assignee }) => {
                if (values.issue) {
                    return { ...values.issue, assignee }
                }
                return values.issue
            },
            updateStatus: ({ status }) => {
                if (values.issue) {
                    return { ...values.issue, status }
                }
                return values.issue
            },
            updateName: ({ name }) => {
                if (values.issue) {
                    return { ...values.issue, name }
                }
                return values.issue
            },
            updateDescription: ({ description }) => {
                if (values.issue) {
                    return { ...values.issue, description }
                }
                return values.issue
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
                const summary = response.results[0]
                if (!summary.aggregations) {
                    return null
                }
                return {
                    first_seen: summary.first_seen,
                    last_seen: summary.last_seen,
                    aggregations: summary.aggregations,
                }
            },
        },
        issueFingerprints: [
            [] as ErrorTrackingFingerprint[],
            {
                loadIssueFingerprints: async () => (await api.errorTracking.fingerprints.list(props.id)).results,
            },
        ],
        similarIssues: [
            [] as SimilarIssue[],
            {
                loadSimilarIssues: async (refresh: boolean = false) => {
                    const query = errorTrackingSimilarIssuesQuery({
                        issueId: props.id,
                        limit: 10,
                        maxDistance: values.similarIssuesMaxDistance,
                    })
                    const response = await api.query(query, {
                        refresh: refresh ? 'force_blocking' : 'blocking',
                    })
                    return response.results
                },
            },
        ],
    })),

    selectors(({ actions }) => ({
        breadcrumbs: [
            (s) => [s.issue],
            (issue: ErrorTrackingRelationalIssue | null): Breadcrumb[] => {
                const exceptionType: string = issue?.name || 'Issue'
                return [
                    {
                        key: Scene.ErrorTracking,
                        name: 'Error tracking',
                        path: urls.errorTracking(),
                        iconType: 'error_tracking',
                    },
                    {
                        key: [Scene.ErrorTrackingIssue, exceptionType],
                        name: exceptionType,
                        onRename: async (name: string) => actions.updateName(name),
                        iconType: 'error_tracking',
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

        eventsQuery: [
            (s) => [s.issueFingerprints, s.filterTestAccounts, s.searchQuery, s.filterGroup, s.dateRange],
            (issueFingerprints, filterTestAccounts, searchQuery, filterGroup, dateRange) =>
                errorTrackingIssueEventsQuery({
                    fingerprints: issueFingerprints.map((f: ErrorTrackingFingerprint) => f.fingerprint),
                    filterTestAccounts,
                    filterGroup,
                    searchQuery,
                    dateRange,
                    columns: ['*', 'timestamp', 'person'],
                }),
        ],

        eventsQueryKey: [
            (s) => [s.eventsQuery],
            () => {
                return uuid()
            },
        ],
    })),

    subscriptions(({ actions }) => ({
        initialEventTimestamp: (value: string | null, oldValue: string | null) => {
            if (!oldValue && value) {
                actions.loadInitialEvent(value)
            }
        },
    })),

    listeners(({ props, values, actions }) => {
        return {
            setDateRange: actions.loadSummary,
            setFilterGroup: actions.loadSummary,
            setFilterTestAccounts: actions.loadSummary,
            setSearchQuery: actions.loadSummary,
            loadSummarySuccess: ({ summary }: { summary: ErrorTrackingIssueSummary | null }) => {
                if (summary && summary.last_seen) {
                    actions.setLastSeen(summary.last_seen)
                    actions.setInitialEventTimestamp(summary.last_seen)
                } else {
                    actions.setInitialEventTimestamp(values.issue?.first_seen ?? null)
                }
            },
            loadIssueFailure: ({ errorObject: { status, data } }) => {
                if (status == 308 && 'issue_id' in data) {
                    router.actions.replace(urls.errorTrackingIssue(data.issue_id))
                }
            },
            updateName: ({ name }) => actions.updateIssueName(props.id, name),
            updateDescription: ({ description }) => actions.updateIssueDescription(props.id, description),
            updateAssignee: ({ assignee }) => actions.updateIssueAssignee(props.id, assignee),
            updateStatus: ({ status }) => actions.updateIssueStatus(props.id, status),
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
            [issueActionsLogic.actionTypes.mutationSuccess]: ({ mutationName }) => {
                if (mutationName === 'mergeIssues') {
                    actions.loadIssue()
                    actions.loadSummary()
                    actions.loadIssueFingerprints()
                }
                if (mutationName === 'createIssueCohort') {
                    actions.loadIssue()
                }
            },
            setSimilarIssuesMaxDistance: () => {
                actions.loadSimilarIssues(true)
            },
        }
    }),

    events(({ props, actions }) => ({
        afterMount: () => {
            actions.loadIssue()
            actions.setInitialEventTimestamp(props.timestamp ?? null)
            actions.loadSummary()
            actions.loadIssueFingerprints()
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
    last_seen?: string
    first_seen?: string
    aggregations: ErrorTrackingIssueAggregations
}
