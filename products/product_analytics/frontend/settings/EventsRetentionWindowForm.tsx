import { useEffect, useState } from 'react'

import { LemonBanner, LemonButton, LemonDialog, LemonInput, LemonLabel, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { LONGEST_PLAN_RETENTION_MONTHS } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'

import { EventsPassSchedule, nextPassOn } from './nextPassOn'
import { retentionPeriodLabel } from './retentionPeriodLabel'

type RetentionChoice = 'default' | 'custom'

export interface EventsRetentionWindowFormProps {
    /** The custom window saved here, or null while the default applies. */
    retentionMonths: number | null
    /** The window that applies while no custom window is saved here. */
    defaultMonths: number
    /** True when the default is the organization's custom window, which deletes at every monthly cleanup. */
    defaultIsOrganizationWindow: boolean
    minMonths: number
    maxMonths: number
    planMonths: number
    /** Whose events the window deletes, as the start of a sentence, e.g. "Events in this project". */
    scope: string
    /** How a custom window here relates to the other settings level. */
    overrideNote: string
    nextMonthlyCleanupOn: string
    /** The current project's pass dates, or null when the default here doesn't apply to the project. */
    passSchedule: EventsPassSchedule | null
    saving: boolean
    restrictionReason: string | null
    onSave: (retentionMonths: number | null) => void
    dataAttr: string
}

function formatDate(date: string): string {
    return dayjs(date).format('MMMM D, YYYY')
}

function monthsProblem(months: number | null, minMonths: number, maxMonths: number): string | null {
    if (months === null || !Number.isInteger(months)) {
        return 'Enter a whole number of months.'
    }
    if (months < minMonths || months > maxMonths) {
        return `Enter a number between ${minMonths} and ${maxMonths}.`
    }
    return null
}

export function EventsRetentionWindowForm({
    retentionMonths,
    defaultMonths,
    defaultIsOrganizationWindow,
    minMonths,
    maxMonths,
    planMonths,
    scope,
    overrideNote,
    nextMonthlyCleanupOn,
    passSchedule,
    saving,
    restrictionReason,
    onSave,
    dataAttr,
}: EventsRetentionWindowFormProps): JSX.Element {
    const [choice, setChoice] = useState<RetentionChoice>(retentionMonths === null ? 'default' : 'custom')
    const [draftMonths, setDraftMonths] = useState<number | null>(retentionMonths ?? defaultMonths)

    useEffect(() => {
        setChoice(retentionMonths === null ? 'default' : 'custom')
        setDraftMonths(retentionMonths ?? defaultMonths)
    }, [retentionMonths, defaultMonths])

    const draftProblem = choice === 'custom' ? monthsProblem(draftMonths, minMonths, maxMonths) : null
    const unchanged = choice === 'default' ? retentionMonths === null : draftMonths === retentionMonths
    const saveDisabledReason =
        restrictionReason ?? (draftProblem !== null ? draftProblem : unchanged ? 'No changes to save' : null)

    const confirmDeletion = (months: number, description: string, onConfirm: () => void): void => {
        LemonDialog.open({
            title: `Are you sure you want to delete events that are older than ${pluralize(months, 'month')}?`,
            description,
            primaryButton: {
                children: "Yes, I'm sure",
                status: 'danger',
                onClick: onConfirm,
                'data-attr': `${dataAttr}-confirm`,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const saveCustom = (months: number): void => {
        const period = pluralize(months, 'month')
        confirmDeletion(
            months,
            `${scope} will be deleted after ${period}. If you have any events that are older than ${period}, they will be deleted at the next monthly cleanup on ${formatDate(nextMonthlyCleanupOn)} and can't be restored.`,
            () => onSave(months)
        )
    }

    const saveDefault = (): void => {
        const savedMonths = retentionMonths === null ? defaultMonths : Math.min(planMonths, retentionMonths)
        const defaultDeletes = defaultIsOrganizationWindow || (passSchedule?.default_window_deletes ?? true)
        if (defaultMonths >= savedMonths || !defaultDeletes) {
            onSave(null)
            return
        }
        const deletesOn = defaultIsOrganizationWindow ? nextMonthlyCleanupOn : passSchedule && nextPassOn(passSchedule)
        const period = pluralize(defaultMonths, 'month')
        confirmDeletion(
            defaultMonths,
            deletesOn
                ? `${scope} will be kept for the default of ${period}. Older events will be deleted at the cleanup on ${formatDate(deletesOn)} and can't be restored.`
                : `${scope} will be kept for the default of ${period}. Older events will be deleted at least 3 months from now and can't be restored.`,
            () => onSave(null)
        )
    }

    const save = (): void => {
        if (saveDisabledReason) {
            return
        }
        if (choice === 'custom' && draftMonths !== null) {
            saveCustom(draftMonths)
        } else {
            saveDefault()
        }
    }

    const canUpgrade = planMonths < LONGEST_PLAN_RETENTION_MONTHS
    const customRange = maxMonths > defaultMonths ? 'shorter or longer' : 'shorter'
    const defaultDescription = defaultIsOrganizationWindow
        ? `This project uses the organization's events retention of ${pluralize(defaultMonths, 'month')}. To set a ${customRange} period for this project, use the Custom events retention setting below.`
        : `Our default retention period for events data is ${pluralize(defaultMonths, 'month')}. To set a ${customRange} period, use the Custom events retention setting below.`

    return (
        <div className="flex flex-col gap-4 max-w-160">
            <LemonLabel>Retention period</LemonLabel>
            <LemonRadio<RetentionChoice>
                value={choice}
                onChange={(value) => {
                    setChoice(value)
                    setDraftMonths(retentionMonths ?? defaultMonths)
                }}
                radioPosition="top"
                aria-label="Retention period"
                data-attr={`${dataAttr}-choice`}
                options={[
                    {
                        value: 'default',
                        label: `Default events retention (${pluralize(defaultMonths, 'month')})`,
                        description: defaultDescription,
                        disabledReason: restrictionReason ?? undefined,
                        'data-attr': `${dataAttr}-default`,
                    },
                    {
                        value: 'custom',
                        label: `Custom events retention (${minMonths} to ${maxMonths} months)`,
                        description:
                            maxMonths > defaultMonths
                                ? `Set a shorter or longer period, up to ${retentionPeriodLabel(maxMonths)}, with a guaranteed deletion date.`
                                : 'Set a shorter period with a guaranteed deletion date.',
                        disabledReason: restrictionReason ?? undefined,
                        'data-attr': `${dataAttr}-custom`,
                    },
                ]}
            />
            {choice === 'custom' && (
                <div className="flex flex-col gap-4 pl-6">
                    <div className="flex flex-col gap-1">
                        <LemonLabel htmlFor={`${dataAttr}-input`}>Keep events for</LemonLabel>
                        <LemonInput
                            id={`${dataAttr}-input`}
                            type="number"
                            min={minMonths}
                            max={maxMonths}
                            value={draftMonths ?? NaN}
                            onChange={(value) =>
                                setDraftMonths(value === undefined || Number.isNaN(value) ? null : value)
                            }
                            onPressEnter={save}
                            status={draftProblem ? 'danger' : 'default'}
                            suffix={<span className="text-secondary">months</span>}
                            disabled={!!restrictionReason || saving}
                            className="w-40"
                            data-attr={`${dataAttr}-input`}
                        />
                        <p className={draftProblem ? 'mb-0 text-xs text-danger' : 'mb-0 text-xs text-secondary'}>
                            {draftProblem ?? `Enter a number between ${minMonths} and ${maxMonths}.`}
                            {draftProblem &&
                                maxMonths === planMonths &&
                                ` Your plan allows up to ${planMonths} months.`}
                        </p>
                    </div>
                    <div className="rounded bg-fill-secondary px-4 py-3 text-xs text-secondary">
                        <p className="mb-2 font-semibold text-primary">How custom retention works</p>
                        <ul className="list-disc pl-4 flex flex-col gap-1">
                            <li>
                                Each monthly cleanup deletes the months whose events are all older than your period, so
                                no event is kept more than about a month past it.
                            </li>
                            <li>Use this if you need a guaranteed deletion date, for example for compliance.</li>
                            <li>{overrideNote}</li>
                            {canUpgrade && (
                                <li>
                                    Need longer data retention? Head over to our{' '}
                                    <Link to={urls.organizationBilling()}>billing page</Link> to upgrade.
                                </li>
                            )}
                        </ul>
                    </div>
                    <LemonBanner type="warning">Deleted events can't be restored.</LemonBanner>
                </div>
            )}
            <div>
                <LemonButton
                    type="primary"
                    onClick={save}
                    loading={saving}
                    disabledReason={saveDisabledReason}
                    data-attr={`${dataAttr}-save`}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
