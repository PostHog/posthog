import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonSegmentedButton, LemonSegmentedButtonOption } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import {
    LOGS_RETENTION_BASE_TIERS_DAYS,
    LOGS_RETENTION_DEFAULT_DAYS,
    LOGS_RETENTION_MAX_MONTHS,
    LOGS_RETENTION_PRESET_DAYS,
    isValidLogsRetentionMonths,
    logsRetentionDaysLabel,
    logsRetentionDaysToMonths,
    logsRetentionMonthsToDays,
} from './logsRetentionPeriod'

const CUSTOM = 'custom'
type PickerValue = number | typeof CUSTOM

const PAID_TIER_DISABLED_REASON = 'Upgrade to a paid plan to keep logs longer than 14 days'

export interface LogsRetentionPeriodPickerProps {
    /** Retention in days. */
    value: number
    onChange: (days: number) => void
    /** Show the 90-day, 1-year and custom options. Off keeps the 14/30-day tiers only. */
    allowCustom: boolean
    /** Disables every option, for access, loading or throttle reasons. */
    disabledReason?: string | null
    /**
     * `change` commits the custom month count as the user types (inside a form with its own save
     * button). `apply` adds an Apply button, for settings that save on every change.
     */
    customCommit?: 'change' | 'apply'
    size?: 'small' | 'medium'
    dataAttrPrefix?: string
}

export function LogsRetentionPeriodPicker({
    value,
    onChange,
    allowCustom,
    disabledReason,
    customCommit = 'change',
    size,
    dataAttrPrefix = 'logs-retention',
}: LogsRetentionPeriodPickerProps): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const hasPaidRetention = hasAvailableFeature(AvailableFeature.LOGS_RETENTION_30D)

    const presetDays = allowCustom ? LOGS_RETENTION_PRESET_DAYS : LOGS_RETENTION_BASE_TIERS_DAYS
    const valueIsPreset = presetDays.includes(value)
    const [customSelected, setCustomSelected] = useState(allowCustom && !valueIsPreset)
    const [customMonths, setCustomMonths] = useState<number | undefined>(logsRetentionDaysToMonths(value))

    // Keep the input in step when the stored value changes from outside, e.g. after a save or reload.
    useEffect(() => {
        if (!valueIsPreset) {
            setCustomSelected(allowCustom)
            setCustomMonths(logsRetentionDaysToMonths(value))
        }
    }, [value, valueIsPreset, allowCustom])

    const paidTierReason = (days: number): string | undefined =>
        days > LOGS_RETENTION_DEFAULT_DAYS && !hasPaidRetention ? PAID_TIER_DISABLED_REASON : undefined

    const options: LemonSegmentedButtonOption<PickerValue>[] = presetDays.map((days) => ({
        value: days,
        label: logsRetentionDaysLabel(days),
        disabledReason: disabledReason ?? paidTierReason(days),
        'data-attr': `${dataAttrPrefix}-button-${days}d`,
    }))
    if (allowCustom) {
        options.push({
            value: CUSTOM,
            label: 'Custom',
            disabledReason: disabledReason ?? (hasPaidRetention ? undefined : PAID_TIER_DISABLED_REASON),
            'data-attr': `${dataAttrPrefix}-button-custom`,
        })
    }

    const customDays = isValidLogsRetentionMonths(customMonths) ? logsRetentionMonthsToDays(customMonths) : undefined
    const customApplyDisabledReason = !isValidLogsRetentionMonths(customMonths)
        ? `Enter a whole number of months from 1 to ${LOGS_RETENTION_MAX_MONTHS}`
        : customDays === value
          ? 'This is the current retention period'
          : undefined

    const handleCustomMonthsChange = (months: number | undefined): void => {
        setCustomMonths(months)
        if (customCommit === 'change' && isValidLogsRetentionMonths(months)) {
            onChange(logsRetentionMonthsToDays(months))
        }
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonSegmentedButton<PickerValue>
                value={customSelected ? CUSTOM : value}
                onChange={(selected) => {
                    if (selected === CUSTOM) {
                        setCustomSelected(true)
                        return
                    }
                    setCustomSelected(false)
                    onChange(selected)
                }}
                options={options}
                size={size}
                disabledReason={disabledReason ?? undefined}
            />
            {customSelected && (
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonInput
                        type="number"
                        size={size}
                        className="w-24"
                        min={1}
                        max={LOGS_RETENTION_MAX_MONTHS}
                        step={1}
                        value={customMonths}
                        onChange={handleCustomMonthsChange}
                        disabledReason={disabledReason}
                        data-attr={`${dataAttrPrefix}-custom-months`}
                    />
                    <span className="text-secondary text-sm">
                        months{customDays !== undefined ? ` (${customDays} days)` : ''}
                    </span>
                    {customCommit === 'apply' && (
                        <LemonButton
                            type="secondary"
                            size={size}
                            onClick={() => customDays !== undefined && onChange(customDays)}
                            disabledReason={disabledReason ?? customApplyDisabledReason}
                            data-attr={`${dataAttrPrefix}-custom-apply`}
                        >
                            Apply
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
}
