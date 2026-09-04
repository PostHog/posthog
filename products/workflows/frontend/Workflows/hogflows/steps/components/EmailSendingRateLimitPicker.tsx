import { useEffect, useState } from 'react'

import { IconClock, IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import type { HogFlowEmailSendingRateLimitApi } from 'products/workflows/frontend/generated/api.schemas'

const DEFAULT_RATE_LIMIT: HogFlowEmailSendingRateLimitApi = { count: 100, period: 'minute' }

export interface EmailSendingRateLimitPickerProps {
    value: HogFlowEmailSendingRateLimitApi | null
    onChange: (value: HogFlowEmailSendingRateLimitApi | null) => void
}

/**
 * Editor for a flow's email pacing, shared by the workflow trigger panel and the broadcast wizard.
 * Callers decide when to show it, because the conditions differ: a workflow needs an email step
 * before pacing means anything, while a broadcast always has one.
 */
export function EmailSendingRateLimitPicker({ value, onChange }: EmailSendingRateLimitPickerProps): JSX.Element {
    // Mirror the count locally so clearing the field doesn't snap back to the committed value
    // mid-edit; reconcile when the stored value changes externally (toggle, another editor).
    const [displayCount, setDisplayCount] = useState<number | undefined>(value?.count)
    useEffect(() => {
        setDisplayCount(value?.count)
    }, [value?.count])

    return (
        <div className="flex flex-col w-full py-2 gap-2">
            <span className="flex gap-1 items-center">
                <IconClock className="text-lg" />
                <span className="text-md font-semibold">Email sending rate limit (optional)</span>
                <Tooltip title="Sending a large volume too quickly can hurt deliverability. Emails over the limit are delayed until capacity frees up, not dropped.">
                    <IconInfo className="text-secondary" />
                </Tooltip>
            </span>
            <p className="mb-0">Spread the emails out over time instead of sending all at once.</p>
            <LemonCheckbox
                checked={!!value}
                onChange={(checked) => onChange(checked ? DEFAULT_RATE_LIMIT : null)}
                label="Limit sending rate"
                data-attr="workflow-email-rate-limit-toggle"
            />
            {value ? (
                <div className="flex items-center gap-2">
                    <span>Send at most</span>
                    <LemonInput
                        type="number"
                        size="small"
                        className="w-24"
                        min={1}
                        // Mirror the API's accepted range (min_value=1, max_value=1_000_000) so an
                        // out-of-range entry is clamped here instead of failing the save.
                        max={1_000_000}
                        aria-label="Maximum emails per period"
                        value={displayCount ?? NaN}
                        onChange={(count) => {
                            if (count == null || !Number.isFinite(count)) {
                                setDisplayCount(undefined)
                                return
                            }
                            const next = Math.min(1_000_000, Math.max(1, Math.floor(count)))
                            setDisplayCount(next)
                            onChange({ ...value, count: next })
                        }}
                        onBlur={() =>
                            displayCount === undefined
                                ? setDisplayCount(value.count)
                                : onChange({ ...value, count: displayCount })
                        }
                        data-attr="workflow-email-rate-limit-count"
                    />
                    <span>emails per</span>
                    <LemonSelect
                        size="small"
                        aria-label="Rate limit period"
                        value={value.period}
                        options={[
                            { value: 'minute' as const, label: 'minute' },
                            { value: 'hour' as const, label: 'hour' },
                        ]}
                        onChange={(period) => onChange({ ...value, period })}
                        data-attr="workflow-email-rate-limit-period"
                    />
                </div>
            ) : null}
        </div>
    )
}
