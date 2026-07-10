import {
    actions,
    connect,
    defaults,
    events,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import {
    ErrorEventProperties,
    ErrorEventType,
    ErrorTrackingFingerprint,
    ErrorTrackingSpikeEvent,
} from 'lib/components/Errors/types'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { Dayjs, dayjs } from 'lib/dayjs'
import { objectsEqual } from 'lib/utils/objects'
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
import { projectLogic } from 'scenes/projectLogic'
import { Scene } from 'scenes/sceneTypes'
import { Params } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import {
    DateRange,
    ErrorTrackingExternalReference,
    ErrorTrackingIssue,
    ErrorTrackingIssueAggregations,
    ErrorTrackingRelationalIssue,
    SimilarIssue,
} from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb, IntegrationType, UniversalFiltersGroup } from '~/types'

import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import {
    DEFAULT_DATE_RANGE,
    issueFiltersLogic,
    triggerFilterActions,
    updateFilterSearchParams,
} from '../../components/IssueFilters/issueFiltersLogic'
import { errorTrackingIssuesResolveRetrieve } from '../../generated/api'
import type { ErrorTrackingIssueResolveResponseApi } from '../../generated/api.schemas'
import { errorTrackingIssueEventsQuery, errorTrackingIssueQuery, errorTrackingSimilarIssuesQuery } from '../../queries'
import { syncSearchParams } from '../../utils'
import { ERROR_TRACKING_DETAILS_RESOLUTION, dateRangeToIsoBounds } from '../../utils'
import {
    DEFAULT_CATEGORY,
    ErrorTrackingIssueSceneCategory,
    VALID_CATEGORIES,
    errorTrackingIssueSceneConfigurationLogic,
} from './errorTrackingIssueSceneConfigurationLogic'
import type { errorTrackingIssueSceneLogicType } from './errorTrackingIssueSceneLogicType'

export interface ErrorTrackingIssueSceneLogicProps {
    identifier: string
    legacyFingerprint?: boolean
    isScene?: boolean
    timestamp?: string
}

export function parseErrorTrackingIssueSceneIdentifier(
    encodedIdentifier: string,
    legacyFingerprint?: string
): Pick<ErrorTrackingIssueSceneLogicProps, 'identifier' | 'legacyFingerprint'> {
    if (legacyFingerprint) {
        return { identifier: legacyFingerprint, legacyFingerprint: true }
    }
    return { identifier: decodeURIComponent(encodedIdentifier), legacyFingerprint: false }
}

export type ErrorTrackingIssueSceneIssue = ErrorTrackingRelationalIssue &
    Partial<Pick<ErrorTrackingIssueResolveResponseApi, 'matched_by'>>

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
    key((props) => `identifier:${props.identifier}`),

    connect(() => ({
        values: [
            issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }),
            ['dateRange', 'filterTestAccounts', 'filterGroup', 'searchQuery'],
            errorTrackingIssueSceneConfigurationLogic,
            ['category'],
            projectLogic,
            ['currentProjectId'],
        ],
        actions: [
            issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }),
            ['setDateRange', 'setFilterTestAccounts', 'setFilterGroup', 'setSearchQuery'],
            issueActionsLogic,
            ['updateIssueAssignee', 'updateIssueStatus', 'updateIssueName', 'updateIssueDescription'],
            errorTrackingIssueSceneConfigurationLogic,
            ['setCategory'],
        ],
    })),

    actions({
        loadIssue: true,
        loadSummary: true,
        loadInitialEvent: (timestamp: string) => ({ timestamp }),
        setMobileDetailOpen: (mobileDetailOpen: boolean) => ({ mobileDetailOpen }),
        setInitialEventTimestamp: (timestamp: string | null) => ({ timestamp }),
        setIssue: (issue: ErrorTrackingRelationalIssue) => ({ issue }),
        canonicalizeIssueUrl: (issue: ErrorTrackingIssueSceneIssue) => ({ issue }),
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
        setListDateRange: (dateRange: DateRange) => ({ dateRange }),
    }),

    defaults({
        issue: null as ErrorTrackingIssueSceneIssue | null,
        summary: null as ErrorTrackingIssueSummary | null,
        properties: null as ErrorEventProperties | null,
        lastSeen: null as Dayjs | null,
        initialEvent: null as ErrorEventType | null,
        selectedEvent: null as ErrorEventType | null,
        mobileDetailOpen: false as boolean,
        initialEventTimestamp: null as string | null,
        initialEventLoading: true as boolean,
        similarIssuesMaxDistance: 0.2 as number,
        similarIssuesError: null as string | null,
        listDateRange: null as DateRange | null,
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
        similarIssuesError: {
            loadSimilarIssues: () => null,
            loadSimilarIssuesSuccess: () => null,
            loadSimilarIssuesFailure: (_, { error }) => error,
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
        mobileDetailOpen: {
            setMobileDetailOpen: (_, { mobileDetailOpen }) => mobileDetailOpen,
        },
        listDateRange: {
            setListDateRange: (_, { dateRange }) => dateRange,
        },
    })),

    loaders(({ values, actions, props }) => ({
        issue: {
            setIssue: ({ issue }) => issue,
            loadIssue: async () => {
                if (values.currentProjectId === null) {
                    throw new Error('Cannot resolve an error tracking issue without a project')
                }
                const response = await errorTrackingIssuesResolveRetrieve(String(values.currentProjectId), {
                    identifier: props.identifier,
                })
                return toErrorTrackingIssue(response)
            },
            createExternalReference: async ({ integrationId, config }) => {
                if (values.issue) {
                    const response = await api.errorTracking.createExternalReference(
                        values.issue.id,
                        integrationId,
                        config
                    )
                    posthog.capture('error_tracking_issue_pushed', {
                        issue_id: values.issue.id,
                        destination: response.integration.kind,
                    })
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
                const issueId = values.issue?.id
                if (!issueId) {
                    return null
                }
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId,
                        dateRange: getNarrowDateRange(timestamp),
                        filterTestAccounts: false,
                        withAggregations: false,
                        withFirstEvent: false,
                        withLastEvent: true,
                    }),
                    { refresh: 'blocking' }
                )
                const issue = response.results[0]
                if (!issue?.last_event) {
                    return null
                }
                const positionEvent = issue.last_event
                const initialEvent: ErrorEventType = {
                    event: '$exception',
                    uuid: positionEvent.uuid,
                    distinct_id: positionEvent.distinct_id,
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
                const issueId = values.issue?.id
                if (!issueId) {
                    return null
                }
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId,
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
                loadIssueFingerprints: async () => {
                    if (!values.issue?.id) {
                        return []
                    }
                    return await api.errorTracking.fingerprints.list(values.issue.id)
                },
            },
        ],
        similarIssues: [
            [] as SimilarIssue[],
            {
                loadSimilarIssues: async (refresh: boolean = false) => {
                    const issueId = values.issue?.id
                    if (!issueId) {
                        return []
                    }
                    const query = errorTrackingSimilarIssuesQuery({
                        issueId,
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
        spikeEvents: [
            [] as ErrorTrackingSpikeEvent[],
            {
                loadSpikeEvents: async () => {
                    const issueId = values.issue?.id
                    if (!issueId) {
                        return []
                    }
                    const { dateFrom, dateTo } = dateRangeToIsoBounds(values.dateRange)
                    const response = await api.errorTracking.getSpikeEvents({
                        issueIds: [issueId],
                        dateFrom,
                        dateTo,
                    })
                    return response.results
                },
            },
        ],
    })),

    selectors(({ actions }) => ({
        breadcrumbs: [
            (s) => [s.issue, s.listDateRange, s.filterTestAccounts, s.filterGroup, s.searchQuery],
            (
                issue: ErrorTrackingIssueSceneIssue | null,
                listDateRange: DateRange | null,
                filterTestAccounts: boolean,
                filterGroup: UniversalFiltersGroup,
                searchQuery: string
            ): Breadcrumb[] => {
                const exceptionType: string = issue?.name || 'Issue'
                // Use the original list date range for back navigation
                const urlParams = updateFilterSearchParams(
                    {},
                    {
                        dateRange: listDateRange ?? DEFAULT_DATE_RANGE,
                        filterTestAccounts,
                        filterGroup,
                        searchQuery,
                    }
                )

                return [
                    {
                        key: Scene.ErrorTracking,
                        name: 'Error tracking',
                        path: urls.errorTracking(urlParams),
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
            (s) => [s.issueId],
            (issueId: string | null): SidePanelSceneContext | null => {
                return issueId
                    ? {
                          activity_scope: ActivityScope.ERROR_TRACKING_ISSUE,
                          activity_item_id: issueId,
                      }
                    : null
            },
        ],
        issueId: [(s) => [s.issue], (issue: ErrorTrackingIssueSceneIssue | null): string | null => issue?.id ?? null],

        firstSeen: [
            (s) => [s.issue],
            (issue: ErrorTrackingIssueSceneIssue | null) => (issue ? dayjs(issue.first_seen) : null),
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
            // Deep-equal recomputes (e.g. a fingerprints refetch returning the same list) must not
            // produce a new query identity, or the key below remounts the whole events table.
            { resultEqualityCheck: objectsEqual },
        ],

        // The key is the kea key of eventsSourceLogic, whose dataNodeLogic is wired in connect()
        // once per key: it MUST change when the query content changes (that's how a new query
        // reaches the data layer) and must NOT change otherwise — every key change unmounts and
        // remounts the entire events table tree.
        eventsQueryKey: [(s) => [s.eventsQuery], (eventsQuery): string => JSON.stringify(eventsQuery)],

        maxContext: [
            (s) => [s.issue, s.issueId],
            (issue: ErrorTrackingIssueSceneIssue | null, issueId: string | null): MaxContextInput[] => {
                if (!issueId) {
                    return []
                }
                return [
                    createMaxContextHelpers.errorTrackingIssue({
                        id: issueId,
                        name: issue?.name ?? null,
                    }),
                ]
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
            setDateRange: () => {
                if (!values.issue?.id) {
                    return
                }
                actions.loadSummary()
                actions.loadSpikeEvents()
            },
            setFilterGroup: () => {
                if (values.issue?.id) {
                    actions.loadSummary()
                }
            },
            setFilterTestAccounts: () => {
                if (values.issue?.id) {
                    actions.loadSummary()
                }
            },
            setSearchQuery: () => {
                if (values.issue?.id) {
                    actions.loadSummary()
                }
            },
            loadSummarySuccess: ({ summary }: { summary: ErrorTrackingIssueSummary | null }) => {
                if (summary && summary.last_seen) {
                    actions.setLastSeen(summary.last_seen)
                    actions.setInitialEventTimestamp(summary.last_seen)
                } else {
                    actions.setInitialEventTimestamp(values.issue?.first_seen ?? null)
                }
            },
            loadIssueSuccess: ({ issue }: { issue: ErrorTrackingIssueSceneIssue }) => {
                actions.canonicalizeIssueUrl(issue)

                const willRemountAtCanonicalFingerprint =
                    props.isScene &&
                    !props.legacyFingerprint &&
                    issue.matched_by === 'issue_id' &&
                    !!issue.fingerprint &&
                    issue.fingerprint !== props.identifier
                if (willRemountAtCanonicalFingerprint) {
                    return
                }

                actions.setInitialEventTimestamp(props.timestamp ?? null)
                actions.loadSummary()
                actions.loadIssueFingerprints()
                actions.loadSpikeEvents()
            },
            canonicalizeIssueUrl: ({ issue }) => {
                if (!props.isScene) {
                    return
                }

                const canonicalIdentifier = props.legacyFingerprint
                    ? props.identifier
                    : issue.matched_by === 'issue_id'
                      ? issue.fingerprint
                      : null
                if (!canonicalIdentifier) {
                    return
                }

                const searchParams = { ...router.values.searchParams }
                delete searchParams.fingerprint
                router.actions.replace(
                    urls.errorTrackingIssue(canonicalIdentifier),
                    searchParams,
                    router.values.hashParams
                )
            },
            updateName: ({ name }) => {
                if (values.issue?.id) {
                    actions.updateIssueName(values.issue.id, name)
                }
            },
            updateDescription: ({ description }) => {
                if (values.issue?.id) {
                    actions.updateIssueDescription(values.issue.id, description)
                }
            },
            updateAssignee: ({ assignee }) => {
                if (values.issue?.id) {
                    actions.updateIssueAssignee(values.issue.id, assignee)
                }
            },
            updateStatus: ({ status }) => {
                if (values.issue?.id) {
                    actions.updateIssueStatus(values.issue.id, status)
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
            [issueActionsLogic.actionTypes.mutationSuccess]: ({ mutationName }) => {
                if (mutationName === 'mergeIssues') {
                    actions.loadIssue()
                }
                if (mutationName === 'createIssueCohort') {
                    actions.loadIssue()
                }
            },
            setSimilarIssuesMaxDistance: () => {
                if (values.issue?.id) {
                    actions.loadSimilarIssues(true)
                }
            },
        }
    }),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadIssue()
            globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.ViewFirstError)
        },
    })),

    propsChanged(({ actions, props, values }, oldProps) => {
        if (props.isScene && !oldProps.isScene && values.issue) {
            actions.canonicalizeIssueUrl(values.issue)
        }
    }),

    urlToAction(({ actions, values }) => {
        return {
            '**/error_tracking/:identifier': (_, params) => {
                if (values.listDateRange == null) {
                    actions.setListDateRange(params.dateRange ?? DEFAULT_DATE_RANGE)
                }
                triggerFilterActions(params, values, actions)
                const tab = params.tab as ErrorTrackingIssueSceneCategory | undefined
                const category = tab && VALID_CATEGORIES.includes(tab) ? tab : DEFAULT_CATEGORY
                if (category !== values.category) {
                    actions.setCategory(category)
                }
            },
        }
    }),

    actionToUrl(({ values }) => {
        const buildURL = (): ReturnType<typeof syncSearchParams> =>
            syncSearchParams(router, (params: Params) => {
                updateFilterSearchParams(params, values)
                if (values.category === DEFAULT_CATEGORY) {
                    delete params.tab
                } else {
                    params.tab = values.category
                }
                return params
            })

        return {
            setDateRange: buildURL,
            setFilterGroup: buildURL,
            setSearchQuery: buildURL,
            setFilterTestAccounts: buildURL,
            setCategory: buildURL,
        }
    }),
])

const ERROR_TRACKING_ISSUE_STATUSES: ErrorTrackingIssue['status'][] = [
    'archived',
    'active',
    'resolved',
    'pending_release',
    'suppressed',
]

function toErrorTrackingIssue(response: ErrorTrackingIssueResolveResponseApi): ErrorTrackingIssueSceneIssue {
    if (!ERROR_TRACKING_ISSUE_STATUSES.includes(response.status as ErrorTrackingIssue['status'])) {
        throw new Error(`Unknown error tracking issue status: ${response.status}`)
    }

    const assignee: ErrorTrackingRelationalIssue['assignee'] =
        response.assignee?.id != null && (response.assignee.type === 'user' || response.assignee.type === 'role')
            ? {
                  id: response.assignee.id,
                  type: response.assignee.type,
              }
            : null
    const externalIssues: ErrorTrackingExternalReference[] = response.external_issues.map(
        ({ id, integration, external_url }) => ({
            id,
            integration: {
                id: integration.id,
                kind: integration.kind as ErrorTrackingExternalReference['integration']['kind'],
                display_name: integration.display_name,
            },
            external_url,
        })
    )

    return {
        id: response.id,
        fingerprint: response.fingerprint,
        status: response.status as ErrorTrackingIssue['status'],
        name: response.name,
        description: response.description,
        first_seen: response.first_seen as ErrorTrackingRelationalIssue['first_seen'],
        assignee,
        external_issues: externalIssues,
        cohort: response.cohort ?? undefined,
        matched_by: response.matched_by,
    }
}

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
