import { deepEqual as equal } from 'fast-equals'
import { MakeLogicType, actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { isUUIDLike } from 'lib/utils/guards'
import { Params } from 'scenes/sceneTypes'

import {
    ErrorTrackingIssue,
    ErrorTrackingIssueTagFilter,
    ErrorTrackingIssueTagsFilter,
    ErrorTrackingQuery,
    ErrorTrackingQueryIssueSeverity,
} from '~/queries/schema/schema-general'

import type {
    ErrorTrackingIssueAssignee,
    ErrorTrackingOrderBy,
} from '../../../../../frontend/src/queries/schema/schema-general'
import type { ErrorTrackingIssueTagDefinitionApi } from '../../generated/api.schemas'
import { syncSearchParams, updateSearchParams } from '../../utils'
import { issueTagDefinitionsLogic } from '../IssueFilters/issueTagDefinitionsLogic'

export type ErrorTrackingQueryOrderBy = ErrorTrackingQuery['orderBy']
export type ErrorTrackingQueryOrderDirection = ErrorTrackingQuery['orderDirection']
export type ErrorTrackingQueryAssignee = ErrorTrackingQuery['assignee']
export type ErrorTrackingQueryStatus = ErrorTrackingQuery['status']
export type ErrorTrackingQuerySeverity = ErrorTrackingQueryIssueSeverity | null
export type IssueTagsFilter = Required<ErrorTrackingIssueTagsFilter>
export type IssueTagState = keyof IssueTagsFilter

export const ORDER_BY_OPTIONS: Record<ErrorTrackingQueryOrderBy, string> = {
    last_seen: 'Last seen',
    first_seen: 'First seen',
    occurrences: 'Occurrences',
    users: 'Users',
    sessions: 'Sessions',
    severity: 'Severity',
}
const DEFAULT_ORDER_BY: ErrorTrackingQueryOrderBy = 'last_seen'

// A persisted (localStorage) or tool-provided orderBy can hold a value that's no longer a
// valid sort field — e.g. an option that was renamed or removed. Passing it through to the
// query fails the whole page, so anything unrecognized falls back to the default.
export function isValidOrderBy(orderBy: unknown): orderBy is ErrorTrackingQueryOrderBy {
    return typeof orderBy === 'string' && Object.hasOwn(ORDER_BY_OPTIONS, orderBy)
}

const DEFAULT_ORDER_DIRECTION = 'DESC'
const DEFAULT_ASSIGNEE = null
const DEFAULT_STATUS = 'active'
const DEFAULT_SEVERITY = null
const DEFAULT_ISSUE_TAGS = null

// Like isValidOrderBy, but the assignee is an object, so it can be malformed in more ways: a bare
// string, a missing or null id, a type outside user/role, or a resolved {id, type, user} object.
// The query schema forbids unknown keys, so any of those makes every issues query fail with a 400
// while the filter button still renders as unset — and the value is persisted, so it keeps failing
// until someone finds "Remove assignee" in the dropdown. Keep only the two fields the query accepts.
export function sanitizeAssignee(assignee: unknown): ErrorTrackingIssueAssignee | null {
    if (!assignee || typeof assignee !== 'object') {
        return DEFAULT_ASSIGNEE
    }
    const { id, type } = assignee as Partial<ErrorTrackingIssueAssignee>
    if (type === 'user' && typeof id === 'number' && Number.isInteger(id)) {
        return { id, type }
    }
    if (type === 'role' && typeof id === 'string' && isUUIDLike(id)) {
        return { id, type }
    }
    return DEFAULT_ASSIGNEE
}

// The statuses the filter accepts: the query's status union minus archived/pending_release,
// which are deprecated (writes rejected, legacy rows backfilled to resolved) and not offered by
// the picker. Exhaustive over the rest, so removing a status from the schema fails typechecking.
type FilterableStatus = Exclude<NonNullable<ErrorTrackingQueryStatus>, 'archived' | 'pending_release'>
const VALID_STATUSES: Record<FilterableStatus, true> = {
    all: true,
    active: true,
    resolved: true,
    suppressed: true,
}

// Like isValidOrderBy: a persisted (localStorage), URL-provided, or tool-provided status can hold
// a value outside the accepted set (a deprecated or renamed status, or free text produced by an
// AI tool). Passing it through breaks the query or crashes the status filter render, so anything
// unrecognized falls back to the default.
export function isValidStatus(status: unknown): status is FilterableStatus {
    return typeof status === 'string' && Object.hasOwn(VALID_STATUSES, status)
}

const VALID_SEVERITIES: Record<ErrorTrackingQueryIssueSeverity, true> = {
    low: true,
    medium: true,
    high: true,
    critical: true,
}

export function isValidSeverity(severity: unknown): severity is ErrorTrackingQueryIssueSeverity {
    return typeof severity === 'string' && Object.hasOwn(VALID_SEVERITIES, severity)
}

function issueTagsOrDefault(issueTags: IssueTagsFilter): IssueTagsFilter | null {
    return issueTags.has.length || issueTags.hasNot.length ? issueTags : DEFAULT_ISSUE_TAGS
}

function tagKeys(keys: unknown): string[] {
    if (!Array.isArray(keys)) {
        return []
    }
    return [...new Set(keys.filter((key): key is string => typeof key === 'string' && key !== ''))]
}

// Like sanitizeAssignee: the query schema forbids unknown keys, so keep only the fields it accepts.
export function sanitizeIssueTags(issueTags: unknown): IssueTagsFilter | null {
    if (!issueTags || typeof issueTags !== 'object') {
        return DEFAULT_ISSUE_TAGS
    }
    const { has, hasNot } = issueTags as Partial<ErrorTrackingIssueTagsFilter>
    const hasNotKeys = tagKeys(hasNot)
    return issueTagsOrDefault({ has: tagKeys(has).filter((key) => !hasNotKeys.includes(key)), hasNot: hasNotKeys })
}

export function issueTagStateOf(issueTags: IssueTagsFilter | null, key: string): IssueTagState | null {
    if (issueTags?.has.includes(key)) {
        return 'has'
    }
    return issueTags?.hasNot.includes(key) ? 'hasNot' : null
}

// The query ignores a tag that is not enabled, so a filter on one would claim to narrow a list it does not.
function withoutUnknownTags(
    issueTags: IssueTagsFilter | null,
    definitions: Pick<ErrorTrackingIssueTagDefinitionApi, 'key'>[]
): IssueTagsFilter | null {
    if (!issueTags) {
        return issueTags
    }
    const isKnown = (key: string): boolean => definitions.some((definition) => definition.key === key)
    return issueTagsOrDefault({ has: issueTags.has.filter(isKnown), hasNot: issueTags.hasNot.filter(isKnown) })
}

// Definitions that loaded before a link opened never reach the load listener, so the link checks them itself.
// findMounted keeps the definitions request off while the filter is hidden.
function issueTagsFromUrl(raw: unknown): IssueTagsFilter | null {
    const issueTags = sanitizeIssueTags(raw)
    const definitions = issueTagDefinitionsLogic.findMounted()?.values.issueTagDefinitions
    return definitions ? withoutUnknownTags(issueTags, definitions) : issueTags
}

// pinned: search param of links saved before the filter took several tags, which the URL now holds in `issueTags`
const LEGACY_ISSUE_TAG_PARAM = 'issueTag'

function legacyIssueTags(issueTag: unknown): ErrorTrackingIssueTagsFilter | null {
    if (!issueTag || typeof issueTag !== 'object') {
        return null
    }
    const { key, applied } = issueTag as Partial<ErrorTrackingIssueTagFilter>
    if (typeof key !== 'string' || !key || typeof applied !== 'boolean') {
        return null
    }
    return applied ? { has: [key] } : { hasNot: [key] }
}

export interface IssueQueryOptionsLogicProps {
    logicKey: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface issueQueryOptionsLogicValues {
    assignee: ErrorTrackingQueryAssignee | null
    issueTags: IssueTagsFilter | null
    orderBy: ErrorTrackingQueryOrderBy
    orderDirection: ErrorTrackingQueryOrderDirection
    severity: ErrorTrackingQuerySeverity
    status: ErrorTrackingQueryStatus
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface issueQueryOptionsLogicActions {
    setAssignee: (assignee: ErrorTrackingIssue['assignee']) => {
        assignee: ErrorTrackingIssueAssignee | null
    }
    setIssueTagState: (
        key: string,
        state: IssueTagState | null
    ) => {
        key: string
        state: keyof ErrorTrackingIssueTagsFilter | null
    }
    setIssueTags: (issueTags: IssueTagsFilter | null) => {
        issueTags: Required<ErrorTrackingIssueTagsFilter> | null
    }
    setOrderBy: (orderBy: ErrorTrackingQueryOrderBy) => {
        orderBy: ErrorTrackingOrderBy
    }
    setOrderDirection: (orderDirection: ErrorTrackingQueryOrderDirection) => {
        orderDirection: 'ASC' | 'DESC' | undefined
    }
    setSeverity: (severity: ErrorTrackingQuerySeverity) => {
        severity: ErrorTrackingQuerySeverity
    }
    setStatus: (status: ErrorTrackingQueryStatus) => {
        status: import('~/queries/schema/schema-general').ErrorTrackingQueryStatus | undefined
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface issueQueryOptionsLogicMeta {
    key: string
}

export type issueQueryOptionsLogicType = MakeLogicType<
    issueQueryOptionsLogicValues,
    issueQueryOptionsLogicActions,
    IssueQueryOptionsLogicProps,
    issueQueryOptionsLogicMeta
>

export const issueQueryOptionsLogic = kea<issueQueryOptionsLogicType>([
    path(['products', 'error_tracking', 'components', 'IssueQueryOptions', 'issueQueryOptionsLogic']),
    props({} as IssueQueryOptionsLogicProps),
    key(({ logicKey }) => logicKey),

    actions({
        setOrderBy: (orderBy: ErrorTrackingQueryOrderBy) => ({ orderBy }),
        setOrderDirection: (orderDirection: ErrorTrackingQueryOrderDirection) => ({ orderDirection }),
        setAssignee: (assignee: ErrorTrackingIssue['assignee']) => ({ assignee }),
        setSeverity: (severity: ErrorTrackingQuerySeverity) => ({ severity }),
        setStatus: (status: ErrorTrackingQueryStatus) => ({ status }),
        setIssueTags: (issueTags: IssueTagsFilter | null) => ({ issueTags }),
        setIssueTagState: (key: string, state: IssueTagState | null) => ({ key, state }),
    }),

    reducers({
        orderBy: [
            DEFAULT_ORDER_BY as ErrorTrackingQueryOrderBy,
            { persist: true },
            {
                setOrderBy: (_, { orderBy }) => (isValidOrderBy(orderBy) ? orderBy : DEFAULT_ORDER_BY),
            },
        ],
        orderDirection: [
            DEFAULT_ORDER_DIRECTION as ErrorTrackingQueryOrderDirection,
            { persist: true },
            {
                setOrderDirection: (_, { orderDirection }) => orderDirection,
            },
        ],
        assignee: [
            DEFAULT_ASSIGNEE as ErrorTrackingQueryAssignee | null,
            { persist: true },
            {
                setAssignee: (_, { assignee }) => sanitizeAssignee(assignee),
            },
        ],
        status: [
            DEFAULT_STATUS as ErrorTrackingQueryStatus,
            { persist: true },
            {
                setStatus: (_, { status }) => (isValidStatus(status) ? status : DEFAULT_STATUS),
            },
        ],
        severity: [
            DEFAULT_SEVERITY as ErrorTrackingQuerySeverity,
            { persist: true },
            {
                setSeverity: (_, { severity }) => (isValidSeverity(severity) ? severity : DEFAULT_SEVERITY),
            },
        ],
        issueTags: [
            DEFAULT_ISSUE_TAGS as IssueTagsFilter | null,
            {
                setIssueTags: (_, { issueTags }) => sanitizeIssueTags(issueTags),
                setIssueTagState: (issueTags, { key, state }) => {
                    const has = (issueTags?.has ?? []).filter((tagKey) => tagKey !== key)
                    const hasNot = (issueTags?.hasNot ?? []).filter((tagKey) => tagKey !== key)
                    return issueTagsOrDefault({
                        has: state === 'has' ? [...has, key] : has,
                        hasNot: state === 'hasNot' ? [...hasNot, key] : hasNot,
                    })
                },
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        [issueTagDefinitionsLogic.actionTypes.loadIssueTagDefinitionsSuccess]: ({
            issueTagDefinitions,
        }: {
            issueTagDefinitions: ErrorTrackingIssueTagDefinitionApi[]
        }) => {
            const issueTags = withoutUnknownTags(values.issueTags, issueTagDefinitions)
            if (!equal(issueTags, values.issueTags)) {
                actions.setIssueTags(issueTags)
            }
        },
        setOrderBy: ({ orderBy }) => {
            posthog.capture('error_tracking_issues_sorted', {
                sort_by: orderBy,
                sort_direction: values.orderDirection,
            })
        },
        setOrderDirection: ({ orderDirection }) => {
            posthog.capture('error_tracking_issues_sorted', {
                sort_by: values.orderBy,
                sort_direction: orderDirection,
            })
        },
    })),

    actionToUrl(({ values }) => {
        const buildURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'assignee', values.assignee, DEFAULT_ASSIGNEE)
                updateSearchParams(params, 'status', values.status, DEFAULT_STATUS)
                updateSearchParams(params, 'severity', values.severity, DEFAULT_SEVERITY)
                updateSearchParams(params, 'issueTags', values.issueTags, DEFAULT_ISSUE_TAGS)
                delete params[LEGACY_ISSUE_TAG_PARAM]
                updateSearchParams(params, 'orderBy', values.orderBy, DEFAULT_ORDER_BY)
                updateSearchParams(params, 'orderDirection', values.orderDirection, DEFAULT_ORDER_DIRECTION)
                return params
            })
        }

        return {
            setOrderBy: () => buildURL(),
            setStatus: () => buildURL(),
            setSeverity: () => buildURL(),
            setIssueTags: () => buildURL(),
            setIssueTagState: () => buildURL(),
            setAssignee: () => buildURL(),
            setOrderDirection: () => buildURL(),
        }
    }),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (params.orderBy && !equal(params.orderBy, values.orderBy)) {
                if (isValidOrderBy(params.orderBy)) {
                    actions.setOrderBy(params.orderBy)
                }
            }
            // Presence check rather than truthiness, since kea-router decodes `?status=` as ''
            // and bare `?status` as null, which must also reset instead of being ignored.
            if ('status' in params && !equal(params.status, values.status)) {
                // Fall back to the default (which also lets actionToUrl scrub the param) so a
                // stale link doesn't silently keep querying the previously persisted status.
                actions.setStatus(isValidStatus(params.status) ? params.status : DEFAULT_STATUS)
            }
            // Presence check like status, so a link with a cleared assignee resets the persisted one.
            if ('assignee' in params && !equal(params.assignee, values.assignee)) {
                actions.setAssignee(params.assignee)
            }
            const severity = isValidSeverity(params.severity) ? params.severity : DEFAULT_SEVERITY
            if (!equal(severity, values.severity)) {
                actions.setSeverity(severity)
            }
            const issueTags = issueTagsFromUrl(params.issueTags ?? legacyIssueTags(params[LEGACY_ISSUE_TAG_PARAM]))
            if (!equal(issueTags, values.issueTags)) {
                actions.setIssueTags(issueTags)
            }
            if (params.orderDirection && !equal(params.orderDirection, values.orderDirection)) {
                actions.setOrderDirection(params.orderDirection)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    afterMount(({ actions, values }) => {
        // Persisted values are loaded straight into state (bypassing the reducers), so an invalid
        // stored value would otherwise reach the query and break the page. Reset them.
        if (!isValidOrderBy(values.orderBy)) {
            actions.setOrderBy(DEFAULT_ORDER_BY)
        }
        if (!isValidStatus(values.status)) {
            actions.setStatus(DEFAULT_STATUS)
        }
        if (values.severity !== null && !isValidSeverity(values.severity)) {
            actions.setSeverity(DEFAULT_SEVERITY)
        }
        const sanitizedAssignee = sanitizeAssignee(values.assignee)
        if (!equal(values.assignee, sanitizedAssignee)) {
            actions.setAssignee(sanitizedAssignee)
        }
    }),
])
