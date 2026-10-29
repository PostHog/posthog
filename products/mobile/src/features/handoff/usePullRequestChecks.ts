import { useQuery } from '@tanstack/react-query'
import { useFocusEffect } from 'expo-router'
import { useCallback, useState } from 'react'

import { fetchReportPullRequestChecks, reportKeys } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { asRecord } from '@/lib/records'

import { useAppActive } from './useTaskRun'

export const CHECKS_POLL_INTERVAL_MS = 30_000
export type PullRequestChecksStatus = 'checking' | 'passing' | 'failing' | 'pending' | 'none' | 'unavailable'

export interface PullRequestChecksView {
    status: PullRequestChecksStatus
    observedAt?: number
    isRefreshing: boolean
}

const FAILED_CONCLUSIONS = new Set(['failure', 'cancelled', 'timed_out', 'action_required', 'startup_failure'])
const PASSED_CONCLUSIONS = new Set(['success', 'neutral', 'skipped'])

export function pullRequestChecksStatus(checks: unknown): PullRequestChecksStatus {
    if (!Array.isArray(checks)) {
        return 'unavailable'
    }
    if (checks.length === 0) {
        return 'none'
    }
    let pending = false
    let unknown = false
    for (const value of checks) {
        const check = asRecord(value)
        if (!check || typeof check.name !== 'string') {
            unknown = true
            continue
        }
        if (typeof check.conclusion === 'string' && FAILED_CONCLUSIONS.has(check.conclusion)) {
            return 'failing'
        }
        if (check.status === 'queued' || check.status === 'in_progress' || check.status === 'pending') {
            pending = true
        } else if (check.status !== 'completed' || !PASSED_CONCLUSIONS.has(String(check.conclusion))) {
            unknown = true
        }
    }
    return unknown ? 'unavailable' : pending ? 'pending' : 'passing'
}

export function usePullRequestChecks(reportId?: string, pullRequestId?: string, enabled = true): PullRequestChecksView {
    const scope = useProjectScope()
    const live = useDataMode() === 'live'
    const active = useAppActive()
    const [focused, setFocused] = useState(false)
    useFocusEffect(
        useCallback(() => {
            setFocused(true)
            return () => setFocused(false)
        }, [])
    )
    const canFetch = enabled && live && active && focused && !!scope && !!reportId && !!pullRequestId
    const query = useQuery({
        queryKey: [...reportKeys.report(scope, reportId ?? ''), 'pr_checks', pullRequestId ?? ''],
        queryFn: async ({ signal }) => {
            const response = await fetchReportPullRequestChecks(reportId as string, pullRequestId as string, signal)
            return { status: pullRequestChecksStatus(response.checks), observedAt: Date.now() }
        },
        enabled: canFetch,
        retry: false,
        staleTime: 0,
        refetchInterval: canFetch ? CHECKS_POLL_INTERVAL_MS : false,
    })
    if (!enabled || !live || !reportId || !pullRequestId || !scope || query.isError) {
        return { status: 'unavailable', isRefreshing: false }
    }
    if (!query.data) {
        return { status: canFetch ? 'checking' : 'unavailable', isRefreshing: false }
    }
    return { ...query.data, isRefreshing: query.isFetching }
}
