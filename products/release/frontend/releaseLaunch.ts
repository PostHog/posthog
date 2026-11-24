import { Dayjs, dayjs } from 'lib/dayjs'
import { scheduleDateToProjectTzISO } from 'scenes/feature-flags/featureFlagLogic'

import { scheduledChangesCreate } from 'products/feature_flags/frontend/generated/api'

export interface LaunchFlag {
    id: number
    key: string
    active: boolean
}

export interface LaunchFailure {
    flagId: number
    reason: string
    pendingApproval: boolean
}

export interface LaunchResult {
    scheduledFlagIds: number[]
    failures: LaunchFailure[]
}

export function defaultLaunchFlagIds(flags: LaunchFlag[]): number[] {
    return flags.filter((flag) => !flag.active).map((flag) => flag.id)
}

export function launchTimeISO(date: Dayjs, timezone: string): string {
    return scheduleDateToProjectTzISO(date, timezone)
}

export function isLaunchInPast(date: Dayjs, timezone: string, now: Dayjs = dayjs()): boolean {
    return !dayjs(launchTimeISO(date, timezone)).isAfter(now)
}

function launchFailure(flagId: number, error: unknown): LaunchFailure {
    const failure = error as { status?: number; code?: string | null; detail?: string | null; message?: string }
    return {
        flagId,
        reason: failure?.detail || failure?.message || 'The request failed.',
        pendingApproval: failure?.status === 409 && failure?.code === 'change_request_pending',
    }
}

export async function scheduleFlagLaunches(
    projectId: string,
    flagIds: number[],
    scheduledAt: string
): Promise<LaunchResult> {
    const results = await Promise.allSettled(
        flagIds.map((flagId) =>
            scheduledChangesCreate(projectId, {
                record_id: String(flagId),
                model_name: 'FeatureFlag',
                payload: { operation: 'update_status', value: true },
                scheduled_at: scheduledAt,
                is_recurring: false,
            })
        )
    )
    return {
        scheduledFlagIds: flagIds.filter((_, index) => results[index].status === 'fulfilled'),
        failures: results.flatMap((result, index) =>
            result.status === 'rejected' ? [launchFailure(flagIds[index], result.reason)] : []
        ),
    }
}
