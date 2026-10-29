import { useEffect, useState } from 'react'

import { LemonBanner, LemonButton, LemonDialog, LemonInput, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { LONGEST_PLAN_RETENTION_MONTHS } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'

export interface EventsRetentionWindowFormProps {
    retentionMonths: number | null
    minMonths: number
    maxMonths: number
    planMonths: number
    /** Who keeps events for the chosen window, as the start of a sentence, e.g. "This project". */
    keptBy: string
    /** What happens when the window is removed. */
    removedDescription: string
    saving: boolean
    restrictionReason: string | null
    onSave: (retentionMonths: number | null) => void
    dataAttr: string
}

function draftMonthsProblem(
    draftMonths: number | undefined,
    minMonths: number,
    maxMonths: number,
    retentionMonths: number | null
): string | null {
    if (draftMonths === undefined || !Number.isInteger(draftMonths)) {
        return 'Enter a whole number of months'
    }
    if (draftMonths < minMonths || draftMonths > maxMonths) {
        return `Choose between ${minMonths} and ${maxMonths} months`
    }
    if (draftMonths === retentionMonths) {
        return 'No changes to save'
    }
    return null
}

export function EventsRetentionWindowForm({
    retentionMonths,
    minMonths,
    maxMonths,
    planMonths,
    keptBy,
    removedDescription,
    saving,
    restrictionReason,
    onSave,
    dataAttr,
}: EventsRetentionWindowFormProps): JSX.Element {
    const [draftMonths, setDraftMonths] = useState<number | undefined>(retentionMonths ?? undefined)

    useEffect(() => {
        setDraftMonths(retentionMonths ?? undefined)
    }, [retentionMonths])

    const saveDisabledReason =
        restrictionReason ?? draftMonthsProblem(draftMonths, minMonths, maxMonths, retentionMonths)

    const confirmSave = (): void => {
        if (draftMonths === undefined) {
            return
        }
        LemonDialog.open({
            title: `Delete events older than ${draftMonths} months?`,
            description: `${keptBy} keeps events for ${draftMonths} months. Older events are deleted at the next monthly cleanup and can't be restored.`,
            primaryButton: {
                children: 'Delete older events',
                status: 'danger',
                onClick: () => onSave(draftMonths),
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
                onClick: () => onSave(null),
                'data-attr': `${dataAttr}-remove-confirm`,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div>
            <LemonBanner type="warning" className="max-w-160 mb-4">
                Events older than this window are deleted at the next monthly cleanup. Deleted events can't be restored.
            </LemonBanner>
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="number"
                    min={minMonths}
                    max={maxMonths}
                    value={draftMonths}
                    onChange={setDraftMonths}
                    onPressEnter={() => !saveDisabledReason && confirmSave()}
                    placeholder="Not set"
                    suffix={<span className="text-secondary">months</span>}
                    disabled={!!restrictionReason || saving}
                    className="w-40"
                    data-attr={`${dataAttr}-input`}
                />
                <LemonButton
                    type="primary"
                    status="danger"
                    onClick={confirmSave}
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
            <p className="mt-2 mb-0 text-sm text-secondary">
                You can choose between {minMonths} and {maxMonths} months.
                {maxMonths === planMonths && planMonths < LONGEST_PLAN_RETENTION_MONTHS && (
                    <>
                        {' '}
                        Need a longer window? <Link to={urls.organizationBilling()}>Upgrade your plan</Link>.
                    </>
                )}
            </p>
        </div>
    )
}
