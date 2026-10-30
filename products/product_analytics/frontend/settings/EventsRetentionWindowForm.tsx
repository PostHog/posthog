import { useEffect, useState } from 'react'

import { LemonBanner, LemonButton, LemonDialog, LemonInput, LemonSwitch, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { LONGEST_PLAN_RETENTION_MONTHS } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'

import type { EventsRetentionUpdate } from './eventsRetentionSettingsLogic'

export interface EventsRetentionWindowFormProps {
    retentionMonths: number | null
    deleteMonthly: boolean
    /** The window that applies while none is set here. */
    fallbackMonths: number
    minMonths: number
    maxMonths: number
    planMonths: number
    /** Who keeps events for the chosen window, as the start of a sentence, e.g. "This project". */
    keptBy: string
    /** What happens when the window is removed. */
    removedDescription: string
    nextMonthlyCleanupOn: string
    /** The next deletion of the current project's events under this window, if one is scheduled. */
    nextDeletionOn: string | null
    nextDeletionBefore: string | null
    saving: boolean
    restrictionReason: string | null
    onSave: (update: EventsRetentionUpdate) => void
    dataAttr: string
}

function formatDate(date: string): string {
    return dayjs(date).format('MMMM D, YYYY')
}

function draftProblem(
    draftMonths: number | undefined,
    draftDeleteMonthly: boolean,
    minMonths: number,
    maxMonths: number,
    savedMonths: number,
    deleteMonthly: boolean
): string | null {
    if (draftMonths === undefined || !Number.isInteger(draftMonths)) {
        return 'Enter a whole number of months'
    }
    if (draftMonths < minMonths || draftMonths > maxMonths) {
        return `Choose between ${minMonths} and ${maxMonths} months`
    }
    if (draftMonths === savedMonths && draftDeleteMonthly === deleteMonthly) {
        return 'No changes to save'
    }
    return null
}

export function EventsRetentionWindowForm({
    retentionMonths,
    deleteMonthly,
    fallbackMonths,
    minMonths,
    maxMonths,
    planMonths,
    keptBy,
    removedDescription,
    nextMonthlyCleanupOn,
    nextDeletionOn,
    nextDeletionBefore,
    saving,
    restrictionReason,
    onSave,
    dataAttr,
}: EventsRetentionWindowFormProps): JSX.Element {
    const savedMonths = retentionMonths ?? fallbackMonths
    const [draftMonths, setDraftMonths] = useState<number | undefined>(savedMonths)
    const [draftDeleteMonthly, setDraftDeleteMonthly] = useState(deleteMonthly)

    useEffect(() => {
        setDraftMonths(savedMonths)
        setDraftDeleteMonthly(deleteMonthly)
    }, [savedMonths, deleteMonthly])

    const saveDisabledReason =
        restrictionReason ??
        draftProblem(draftMonths, draftDeleteMonthly, minMonths, maxMonths, savedMonths, deleteMonthly)

    const save = (): void => {
        if (draftMonths === undefined) {
            return
        }
        const deletesSooner = draftMonths < savedMonths || (draftDeleteMonthly && !deleteMonthly)
        if (!deletesSooner) {
            onSave({ retentionMonths: draftMonths, deleteMonthly: draftDeleteMonthly })
            return
        }
        LemonDialog.open({
            title: `Delete events older than ${draftMonths} months?`,
            description: draftDeleteMonthly
                ? `${keptBy} keeps events for ${draftMonths} months. Older events are deleted at the next monthly cleanup on ${formatDate(nextMonthlyCleanupOn)} and can't be restored.`
                : `${keptBy} keeps events for ${draftMonths} months. Older events are deleted at the cleanup every 3 months, at least 3 months from now. Deleted events can't be restored.`,
            primaryButton: {
                children: 'Delete older events',
                status: 'danger',
                onClick: () => onSave({ retentionMonths: draftMonths, deleteMonthly: draftDeleteMonthly }),
                'data-attr': `${dataAttr}-confirm`,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const confirmRemove = (): void => {
        LemonDialog.open({
            title: 'Remove this window?',
            description: removedDescription,
            primaryButton: {
                children: 'Remove window',
                onClick: () => onSave({ retentionMonths: null, deleteMonthly: false }),
                'data-attr': `${dataAttr}-remove-confirm`,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div>
            <LemonBanner type="warning" className="max-w-160 mb-4">
                Events older than this window are deleted. Deleted events can't be restored.
            </LemonBanner>
            <div className="flex flex-col gap-2 max-w-160">
                <LemonInput
                    type="number"
                    min={minMonths}
                    max={maxMonths}
                    value={draftMonths}
                    onChange={setDraftMonths}
                    onPressEnter={() => !saveDisabledReason && save()}
                    suffix={<span className="text-secondary">months</span>}
                    disabled={!!restrictionReason || saving}
                    className="w-40"
                    data-attr={`${dataAttr}-input`}
                />
                <p className="mb-0 text-sm text-secondary">
                    You can choose between {minMonths} and {maxMonths} months.
                    {maxMonths === planMonths && planMonths < LONGEST_PLAN_RETENTION_MONTHS && (
                        <>
                            {' '}
                            Need a longer window? <Link to={urls.organizationBilling()}>Upgrade your plan</Link>.
                        </>
                    )}
                </p>
                <LemonSwitch
                    checked={draftDeleteMonthly}
                    onChange={setDraftDeleteMonthly}
                    label="Delete older events every month"
                    disabledReason={restrictionReason ?? (saving ? 'Saving...' : undefined)}
                    bordered
                    data-attr={`${dataAttr}-delete-monthly`}
                />
                <p className="mb-0 text-sm text-secondary">
                    When this is off, older events are deleted every 3 months, and a shorter window waits at least 3
                    months before its first deletion.
                </p>
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton
                        type="primary"
                        onClick={save}
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        data-attr={`${dataAttr}-save`}
                    >
                        Save
                    </LemonButton>
                    {retentionMonths !== null && (
                        <LemonButton
                            type="secondary"
                            onClick={confirmRemove}
                            disabledReason={restrictionReason ?? (saving ? 'Saving...' : null)}
                            data-attr={`${dataAttr}-remove`}
                        >
                            Remove window
                        </LemonButton>
                    )}
                </div>
                {nextDeletionOn && nextDeletionBefore && (
                    <p className="mb-0 text-sm" data-attr={`${dataAttr}-next-deletion`}>
                        Next deletion for this project: {formatDate(nextDeletionOn)}. Events from before{' '}
                        {dayjs(nextDeletionBefore).format('MMMM YYYY')} will be deleted.
                    </p>
                )}
            </div>
        </div>
    )
}
