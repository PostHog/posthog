import { scheduledChangesCreate } from 'products/feature_flags/frontend/generated/api'

export interface LaunchFlag {
    id: number
    key: string
    active: boolean
}

export interface LaunchResult {
    scheduledFlagIds: number[]
    failedFlagIds: number[]
}

export function defaultLaunchFlagIds(flags: LaunchFlag[]): number[] {
    return flags.filter((flag) => !flag.active).map((flag) => flag.id)
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
        failedFlagIds: flagIds.filter((_, index) => results[index].status === 'rejected'),
    }
}
