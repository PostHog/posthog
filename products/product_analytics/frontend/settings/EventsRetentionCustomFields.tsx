import { LemonLabel, LemonSelect, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { LONGEST_PLAN_RETENTION_MONTHS } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'

import { retentionPeriodLabel } from './retentionPeriodLabel'

export interface EventsRetentionCustomFieldsProps {
    months: number | null
    choiceMonths: readonly number[]
    planMonths: number
    overrideNote: string
    disabledReason: string | null
    onChange: (months: number) => void
    dataAttr: string
}

export function EventsRetentionCustomFields({
    months,
    choiceMonths,
    planMonths,
    overrideNote,
    disabledReason,
    onChange,
    dataAttr,
}: EventsRetentionCustomFieldsProps): JSX.Element {
    // Staff can set a period outside the choices, so show it to keep the saved value visible.
    const optionMonths =
        months === null || choiceMonths.includes(months)
            ? choiceMonths
            : [...choiceMonths, months].sort((a, b) => a - b)

    return (
        <div className="flex flex-col gap-4 pl-6">
            <div className="flex flex-col gap-1">
                <LemonLabel htmlFor={`${dataAttr}-select`}>Keep events for</LemonLabel>
                <LemonSelect<number>
                    id={`${dataAttr}-select`}
                    value={months ?? undefined}
                    onChange={onChange}
                    options={optionMonths.map((value) => ({ value, label: retentionPeriodLabel(value) }))}
                    placeholder="Choose a period"
                    disabledReason={disabledReason}
                    className="w-40"
                    data-attr={`${dataAttr}-select`}
                />
            </div>
            <div className="rounded bg-fill-secondary px-4 py-3 text-xs text-secondary">
                <p className="mb-2 font-semibold text-primary">How custom retention works</p>
                <ul className="list-disc pl-4 flex flex-col gap-1">
                    <li>Deletion of older events is not instant. It happens once a month.</li>
                    <li>{overrideNote}</li>
                    {planMonths < LONGEST_PLAN_RETENTION_MONTHS && (
                        <li>
                            Need longer data retention? Head over to our{' '}
                            <Link to={urls.organizationBilling()}>billing page</Link> to upgrade.
                        </li>
                    )}
                </ul>
            </div>
        </div>
    )
}
