import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import { NotSignedInError } from '@/api/client'
import {
    type AvailableReviewersApi,
    fetchAvailableReviewers,
    fetchLatestReviewerArtefact,
    putReportReviewers,
    type ReportArtefactApi,
    reportKeys,
    type SuggestedReviewerWriteApi,
} from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode, useDemoMode } from '@/demo/demoMode'
import { DEMO_PEOPLE } from '@/demo/fixtures'
import { useDemoReportQuery } from '@/demo/hooks'
import { track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'
import { githubOnlyReviewers, reviewersFromArtefacts } from '@/model/adapters/report'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { Person, QueryState, Reviewer } from '@/model/types'

/** `SignalReportArtefactWriteSerializer.MAX_ENTRIES`. GitHub-only reviewers count toward it. */
export const MAX_REVIEWERS = 10

const SEARCH_DEBOUNCE_MS = 250
/** The member list changes rarely, so a search stays fresh for a few minutes. */
const REVIEWERS_STALE_MS = 5 * 60_000

function matches(person: Person, query: string): boolean {
    const q = query.trim().toLowerCase()
    if (!q) {
        return true
    }
    return person.name.toLowerCase().includes(q) || (person.role ?? '').toLowerCase().includes(q)
}

function useDebounced(value: string, delayMs: number): string {
    const [debounced, setDebounced] = useState(value)
    useEffect(() => {
        const timer = setTimeout(() => setDebounced(value), delayMs)
        return () => clearTimeout(timer)
    }, [value, delayMs])
    return debounced
}

function toPeople(members: AvailableReviewersApi): Person[] {
    return Object.entries(members).map(([uuid, member]) => ({
        uuid,
        name: member.name || member.email,
        email: member.email,
    }))
}

export function useAvailableReviewers(query: string): QueryState<Person[]> {
    const mode = useDataMode()
    const scope = useProjectScope()
    const search = useDebounced(query.trim(), SEARCH_DEBOUNCE_MS)
    const people = useMemo(() => DEMO_PEOPLE.filter((person) => matches(person, query)), [query])
    const live = useQuery({
        queryKey: reportKeys.availableReviewers(scope, search),
        queryFn: ({ signal }) => fetchAvailableReviewers(search, signal),
        enabled: mode === 'live' && scope !== null,
        staleTime: REVIEWERS_STALE_MS,
        placeholderData: keepPreviousData,
        select: toPeople,
    })
    if (mode === 'loading') {
        return loadingQuery()
    }
    if (mode === 'demo') {
        return successQuery(people)
    }
    if (!scope) {
        return errorQuery(new NotSignedInError())
    }
    if (live.data) {
        return successQuery(live.data, { isRefetching: live.isFetching, refetch: live.refetch })
    }
    if (live.isError) {
        return { ...errorQuery<Person[]>(toError(live.error), live.refetch), isRefetching: live.isFetching }
    }
    return { ...loadingQuery<Person[]>(), refetch: live.refetch }
}

/** Reviewers known only by a GitHub login. The sheet cannot list them, but the save sends them back. */
export function useGithubOnlyReviewerCount(reportId: string): number {
    const mode = useDataMode()
    const scope = useProjectScope()
    const count = useQuery({
        queryKey: reportKeys.reviewers(scope, reportId),
        queryFn: ({ signal }) => fetchLatestReviewerArtefact(reportId, signal),
        enabled: mode === 'live' && scope !== null,
        select: (data) => githubOnlyReviewers(data ? [data] : []).length,
    })
    return mode === 'live' ? (count.data ?? 0) : 0
}

function selectReviewers(data: ReportArtefactApi | null): Reviewer[] {
    return reviewersFromArtefacts(data ? [data] : [])
}

// Reads only the work log, so a caller outside the report screen gets the reviewers without the report's refetches.
export function useReportReviewers(reportId: string): Reviewer[] | undefined {
    return useReportReviewersQuery(reportId).data
}

export function useReportReviewersQuery(reportId: string): QueryState<Reviewer[]> {
    const mode = useDataMode()
    const scope = useProjectScope()
    const demo = useDemoReportQuery(reportId)
    const live = useQuery({
        queryKey: reportKeys.reviewers(scope, reportId),
        queryFn: ({ signal }) => fetchLatestReviewerArtefact(reportId, signal),
        enabled: mode === 'live' && scope !== null,
        select: selectReviewers,
    })
    if (mode === 'demo') {
        return demo.data ? successQuery(demo.data.reviewers) : errorQuery(demo.error ?? new Error('Report unavailable'))
    }
    if (mode === 'loading') {
        return loadingQuery()
    }
    if (!scope) {
        return errorQuery(new NotSignedInError())
    }
    if (live.data) {
        return successQuery(live.data, { isRefetching: live.isFetching, refetch: live.refetch })
    }
    if (live.isError && !live.isFetching) {
        return errorQuery(toError(live.error), live.refetch)
    }
    return { ...loadingQuery<Reviewer[]>(), refetch: live.refetch }
}

export function useSetReviewersAction(reportId: string): AsyncAction<[string[]]> {
    const demo = useDemoMode((state) => state.enabled)
    const demoSetReviewers = useDemoMode((state) => state.setReviewers)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    return useAsyncAction(async (uuids: string[]) => {
        if (demo) {
            demoSetReviewers(reportId, uuids)
            return
        }
        if (!scope) {
            throw new NotSignedInError()
        }
        // The sheet only lists PostHog users. Reviewers known only by GitHub login go back unchanged,
        // because the PUT replaces the whole list.
        const latest = await fetchLatestReviewerArtefact(reportId)
        const githubOnly = githubOnlyReviewers(latest ? [latest] : [])
        const content: SuggestedReviewerWriteApi[] = [
            ...[...new Set(uuids)].map((uuid) => ({ user_uuid: uuid })),
            ...githubOnly.map((login) => ({ github_login: login })),
        ]
        await putReportReviewers(reportId, content)
        track('mobile_reviewers_changed', { report_id: reportId, count: uuids.length })
        void queryClient.invalidateQueries({ queryKey: reportKeys.inbox(scope) })
        // The sheet closes when this resolves, so wait for the work log that names the new reviewers.
        await queryClient.invalidateQueries({ queryKey: reportKeys.artefacts(scope, reportId) })
    })
}
