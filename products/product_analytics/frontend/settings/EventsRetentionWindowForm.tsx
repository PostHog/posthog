import { useEffect, useState } from 'react'

import { LemonBanner, LemonButton, LemonDialog, LemonInput, LemonSwitch, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { LONGEST_PLAN_RETENTION_MONTHS } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'

import type { EventsRetentionUpdate } from './eventsRetentionSettingsLogic'
import { EventsPassSchedule, nextPassOn } from './nextPassOn'

export interface EventsRetentionFallback {
    months: number
    deleteMonthly: boolean
    /** False when the fallback is the default window rather than one set in settings. */
    isSet: boolean
    /** The fallback as the end of a sentence, e.g. "the default window of 24 months". */
    description: string
}

export interface EventsRetentionWindowFormProps {
    retentionMonths: number | null
    deleteMonthly: boolean
    /** The window that applies while none is set here. */
    fallback: EventsRetentionFallback
    minMonths: number
    maxMonths: number
    planMonths: number
    /** Who keeps events for the chosen window, as the start of a sentence, e.g. "This project". */
    keptBy: string
    nextMonthlyCleanupOn: string
    /** The current project's pass dates, or null when this window doesn't apply to the project. */
    passSchedule: EventsPassSchedule | null
    saving: boolean
    restrictionReason: string | null
    onSave: (update: EventsRetentionUpdate) => void
    dataAttr: string
}

interface EffectiveWindow {
    months: number
    deleteMonthly: boolean
    isSet: boolean
}

function formatDate(date: string): string {
    return dayjs(date).format('MMMM D, YYYY')
}

function effectiveWindow(
    months: number | null,
    deleteMonthly: boolean,
    fallback: EventsRetentionFallback,
    planMonths: number
): EffectiveWindow {
    return months === null
        ? {
              months: Math.min(planMonths, fallback.months),
              deleteMonthly: fallback.deleteMonthly,
              isSet: fallback.isSet,
          }
        : { months: Math.min(planMonths, months), deleteMonthly, isSet: true }
}

function draftProblem(
    draftMonths: number | null,
    draftDeleteMonthly: boolean,
    retentionMonths: number | null,
    deleteMonthly: boolean,
    minMonths: number,
    maxMonths: number
): string | null {
    if (draftMonths !== null && !Number.isInteger(draftMonths)) {
        return 'Enter a whole number of months'
    }
    if (draftMonths !== null && (draftMonths < minMonths || draftMonths > maxMonths)) {
        return `Choose between ${minMonths} and ${maxMonths} months`
    }
    const unchanged = draftMonths === retentionMonths && (draftMonths === null || draftDeleteMonthly === deleteMonthly)
    return unchanged ? 'No changes to save' : null
}

export function EventsRetentionWindowForm({
    retentionMonths,
    deleteMonthly,
    fallback,
    minMonths,
    maxMonths,
    planMonths,
    keptBy,
    nextMonthlyCleanupOn,
    passSchedule,
    saving,
    restrictionReason,
    onSave,
    dataAttr,
}: EventsRetentionWindowFormProps): JSX.Element {
    const [draftMonths, setDraftMonths] = useState<number | null>(retentionMonths)
    const [draftDeleteMonthly, setDraftDeleteMonthly] = useState(deleteMonthly)

    useEffect(() => {
        setDraftMonths(retentionMonths)
        setDraftDeleteMonthly(deleteMonthly)
    }, [retentionMonths, deleteMonthly])

    const saved = effectiveWindow(retentionMonths, deleteMonthly, fallback, planMonths)
    const draft = effectiveWindow(draftMonths, draftDeleteMonthly, fallback, planMonths)
    const deletesOn = draft.deleteMonthly
        ? nextMonthlyCleanupOn
        : passSchedule && nextPassOn(passSchedule, { isSet: draft.isSet, isShorter: draft.months < saved.months })
    const saveDisabledReason =
        restrictionReason ??
        draftProblem(draftMonths, draftDeleteMonthly, retentionMonths, deleteMonthly, minMonths, maxMonths)

    const save = (): void => {
        const update = { retentionMonths: draftMonths, deleteMonthly: draftMonths !== null && draftDeleteMonthly }
        const deletesSooner = draft.months < saved.months || (draft.deleteMonthly && !saved.deleteMonthly)
        if (!deletesSooner) {
            onSave(update)
            return
        }
        LemonDialog.open({
            title: `Delete events older than ${draft.months} months?`,
            description: deletesOn
                ? `${keptBy} keeps events for ${draft.months} months. Older events will be deleted on ${formatDate(deletesOn)} and can't be restored.`
                : `${keptBy} keeps events for ${draft.months} months. Older events will be deleted at least 3 months from now and can't be restored.`,
            primaryButton: {
                children: 'Delete older events',
                status: 'danger',
                onClick: () => onSave(update),
                'data-attr': `${dataAttr}-confirm`,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div>
            <LemonBanner type="warning" className="max-w-160 mb-4">
                Events older than this window will be deleted. Deleted events can't be restored.
            </LemonBanner>
            <div className="flex flex-col gap-2 max-w-160">
                <LemonInput
                    type="number"
                    min={minMonths}
                    max={maxMonths}
                    value={draftMonths ?? NaN}
                    onChange={(value) => setDraftMonths(value === undefined || Number.isNaN(value) ? null : value)}
                    onPressEnter={() => !saveDisabledReason && save()}
                    placeholder={String(fallback.months)}
                    suffix={<span className="text-secondary">months</span>}
                    disabled={!!restrictionReason || saving}
                    className="w-40"
                    data-attr={`${dataAttr}-input`}
                />
                <p className="mb-0 text-sm text-secondary">
                    {`Leave empty to use ${fallback.description}. You can choose between ${minMonths} and ${maxMonths} months.`}
                    {maxMonths === planMonths && planMonths < LONGEST_PLAN_RETENTION_MONTHS && (
                        <>
                            {' '}
                            Need a longer window? <Link to={urls.organizationBilling()}>Upgrade your plan</Link>.
                        </>
                    )}
                </p>
                <LemonSwitch
                    checked={draftMonths === null ? fallback.deleteMonthly : draftDeleteMonthly}
                    onChange={setDraftDeleteMonthly}
                    label={`Delete at the next monthly cleanup on ${formatDate(nextMonthlyCleanupOn)}`}
                    disabledReason={
                        restrictionReason ??
                        (saving ? 'Saving...' : draftMonths === null ? 'Enter a window to change this' : undefined)
                    }
                    bordered
                    data-attr={`${dataAttr}-delete-monthly`}
                />
                <div className="text-sm" data-attr={`${dataAttr}-next-deletion`}>
                    {deletesOn && (
                        <p className="mb-0">
                            Next deletion: <span translate="no">{formatDate(deletesOn)}</span>. Events from before{' '}
                            <span translate="no">
                                {dayjs(deletesOn).subtract(draft.months, 'month').format('MMMM YYYY')}
                            </span>{' '}
                            will be deleted.
                        </p>
                    )}
                    <p className="mb-0 text-secondary">
                        {draft.deleteMonthly
                            ? 'After that, deletions run every month.'
                            : 'Deletions run every 3 months. A shorter window waits at least 3 months.'}
                    </p>
                </div>
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
        </div>
    )
}
