import clsx from 'clsx'

import { LemonBanner, LemonInput, LemonLabel, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { LONGEST_PLAN_RETENTION_MONTHS } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'

export interface EventsRetentionCustomFieldsProps {
    months: number | null
    problem: string | null
    minMonths: number
    maxMonths: number
    planMonths: number
    overrideNote: string
    disabled: boolean
    onChange: (months: number | null) => void
    onPressEnter: () => void
    dataAttr: string
}

export function EventsRetentionCustomFields({
    months,
    problem,
    minMonths,
    maxMonths,
    planMonths,
    overrideNote,
    disabled,
    onChange,
    onPressEnter,
    dataAttr,
}: EventsRetentionCustomFieldsProps): JSX.Element {
    const hint = problem ?? `Enter a number between ${minMonths} and ${maxMonths}.`
    const planLimit = problem && maxMonths === planMonths ? ` Your plan allows up to ${planMonths} months.` : ''

    return (
        <div className="flex flex-col gap-4 pl-6">
            <div className="flex flex-col gap-1">
                <LemonLabel htmlFor={`${dataAttr}-input`}>Keep events for</LemonLabel>
                <LemonInput
                    id={`${dataAttr}-input`}
                    type="number"
                    min={minMonths}
                    max={maxMonths}
                    value={months ?? NaN}
                    onChange={(value) => onChange(value === undefined || Number.isNaN(value) ? null : value)}
                    onPressEnter={onPressEnter}
                    status={problem ? 'danger' : 'default'}
                    suffix={<span className="text-secondary">months</span>}
                    disabled={disabled}
                    className="w-40"
                    data-attr={`${dataAttr}-input`}
                />
                <p className={clsx('mb-0 text-xs', problem ? 'text-danger' : 'text-secondary')}>
                    {hint}
                    {planLimit}
                </p>
            </div>
            <div className="rounded bg-fill-secondary px-4 py-3 text-xs text-secondary">
                <p className="mb-2 font-semibold text-primary">How custom retention works</p>
                <ul className="list-disc pl-4 flex flex-col gap-1">
                    <li>
                        Each monthly cleanup deletes the months whose events are all older than your period, so no event
                        is kept more than about a month past it.
                    </li>
                    <li>Use this if you need a guaranteed deletion date, for example for compliance.</li>
                    <li>{overrideNote}</li>
                    {planMonths < LONGEST_PLAN_RETENTION_MONTHS && (
                        <li>
                            Need longer data retention? Head over to our{' '}
                            <Link to={urls.organizationBilling()}>billing page</Link> to upgrade.
                        </li>
                    )}
                </ul>
            </div>
            <LemonBanner type="warning">Deleted events can't be restored.</LemonBanner>
        </div>
    )
}
