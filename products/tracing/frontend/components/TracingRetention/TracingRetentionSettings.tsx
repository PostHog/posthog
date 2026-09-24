import { useActions, useValues } from 'kea'

import { LemonDialog } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import {
    isValidLogsRetentionDays,
    logsRetentionDaysLabel,
} from 'products/logs/frontend/components/LogsRetention/logsRetentionPeriod'
import { LogsRetentionPeriodPicker } from 'products/logs/frontend/components/LogsRetention/LogsRetentionPeriodPicker'
import { RetentionRulesSection } from 'products/logs/frontend/components/LogsRetention/LogsRetentionSection'
import { TracingFeatureFlagKeys } from 'products/tracing/frontend/tracingFeatureFlagKeys'

import { TRACES_RETENTION_DEFAULT_DAYS, tracingRetentionConfigLogic } from './tracingRetentionConfigLogic'
import { TRACES_RETENTION_PRODUCT } from './tracingRetentionProduct'

export function TracingRetentionSettings(): JSX.Element {
    const { retentionDays, retentionLastUpdated, tracingConfigLoading } = useValues(tracingRetentionConfigLogic)
    const { updateRetentionDays } = useActions(tracingRetentionConfigLogic)
    const allowCustomRetention = useFeatureFlag(TracingFeatureFlagKeys.customRetention)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    // Show any stored period the backend accepts, even when the flag that offered it is now off.
    const currentRetention = isValidLogsRetentionDays(retentionDays, true)
        ? retentionDays
        : TRACES_RETENTION_DEFAULT_DAYS

    const getThrottleReason = (): string | undefined => {
        if (!retentionLastUpdated) {
            return undefined
        }
        const hoursSinceUpdate = dayjs().diff(dayjs(retentionLastUpdated), 'hours')
        if (hoursSinceUpdate < 24) {
            const hoursRemaining = Math.max(1, 24 - hoursSinceUpdate)
            return `You can update retention again in ${hoursRemaining} hour${hoursRemaining !== 1 ? 's' : ''}`
        }
        return undefined
    }

    const disabledReason = tracingConfigLoading ? 'Loading...' : (restrictedReason ?? getThrottleReason())

    const handleRetentionChange = (retentionDaysValue: number): void => {
        if (retentionDaysValue === currentRetention) {
            return
        }
        LemonDialog.open({
            title: 'Change traces retention period?',
            description:
                'Changing retention only affects spans from this point forwards. Existing spans keep their original retention period.',
            primaryButton: {
                children: `Change retention to ${logsRetentionDaysLabel(retentionDaysValue)}`,
                onClick: () => updateRetentionDays(retentionDaysValue),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Tracing}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LogsRetentionPeriodPicker
                value={currentRetention}
                onChange={handleRetentionChange}
                allowCustom={allowCustomRetention}
                requiresPaidRetention={false}
                disabledReason={disabledReason}
                customCommit="apply"
                dataAttrPrefix="tracing-retention"
            />
        </AccessControlAction>
    )
}

/** Environment default plus the span retention rules, the same block shape as Logs. */
export function TracingRetentionSettingsBlock(): JSX.Element {
    const rulesEnabled = useFeatureFlag(TracingFeatureFlagKeys.retentionRules)
    return (
        <div className="flex flex-col gap-4">
            <TracingRetentionSettings />
            {rulesEnabled && <RetentionRulesSection product={TRACES_RETENTION_PRODUCT} />}
        </div>
    )
}
