import { useEffect, useState } from 'react'

import { LemonButton, LemonDialog, LemonLabel, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { urls } from 'scenes/urls'

import type { EventsRetentionImpactApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { defaultDeletesMore } from './defaultDeletesMore'
import { EventsRetentionCustomFields } from './EventsRetentionCustomFields'
import { EventsRetentionImpactNote } from './EventsRetentionImpactNote'
import { EventsPassSchedule, nextPassOn } from './nextPassOn'
import { retentionPeriodLabel } from './retentionPeriodLabel'

type RetentionChoice = 'default' | 'custom'

export interface EventsRetentionPeriodFormProps {
    retentionMonths: number | null
    defaultMonths: number
    defaultSource: 'plan' | 'organization'
    monthlyDefaultMonths: number | null
    maxMonths: number
    choiceMonths: readonly number[]
    planMonths: number
    scope: string
    overrideNote: string
    nextMonthlyCleanupOn: string
    passSchedule: EventsPassSchedule | null
    saving: boolean
    restrictionReason: string | null
    onSave: (retentionMonths: number | null) => void
    impact: EventsRetentionImpactApi | null
    impactLoading: boolean
    onCountImpact: (retentionMonths: number) => void
    dataAttr: string
}

function formatDate(date: string): string {
    return dayjs(date).format('MMMM D, YYYY')
}

function retentionChoiceOptions({
    defaultMonths,
    defaultSource,
    maxMonths,
    restrictionReason,
    dataAttr,
}: EventsRetentionPeriodFormProps): LemonRadioOption<RetentionChoice>[] {
    const canLengthen = maxMonths > defaultMonths
    const range = canLengthen ? 'shorter or longer' : 'shorter'
    const defaultPeriod = retentionPeriodLabel(defaultMonths)
    const disabledReason = restrictionReason ?? undefined
    return [
        {
            value: 'default',
            label: `${defaultSource === 'organization' ? 'Organization' : 'Default'} events retention (${defaultPeriod})`,
            description:
                defaultSource === 'organization' ? (
                    <>
                        This project uses the organization's events retention of {defaultPeriod}, which you can change
                        in{' '}
                        <Link to={urls.settings('organization-details', 'organization-events-retention')}>
                            organization settings
                        </Link>
                        . To set a {range} period for this project only, use the Custom events retention setting below.
                    </>
                ) : (
                    `Our default retention period for events data is ${defaultPeriod}. To set a ${range} period, use the Custom events retention setting below.`
                ),
            disabledReason,
            'data-attr': `${dataAttr}-default`,
        },
        {
            value: 'custom',
            label: 'Custom events retention',
            description: canLengthen
                ? `Set a shorter or longer period, up to ${retentionPeriodLabel(maxMonths)}.`
                : 'Set a shorter period.',
            disabledReason,
            'data-attr': `${dataAttr}-custom`,
        },
    ]
}

export function EventsRetentionPeriodForm(props: EventsRetentionPeriodFormProps): JSX.Element {
    const {
        retentionMonths,
        defaultMonths,
        monthlyDefaultMonths,
        choiceMonths,
        planMonths,
        scope,
        overrideNote,
        nextMonthlyCleanupOn,
        passSchedule,
        saving,
        restrictionReason,
        onSave,
        impact,
        impactLoading,
        onCountImpact,
        dataAttr,
    } = props
    const savedChoice: RetentionChoice = retentionMonths === null ? 'default' : 'custom'
    const [choice, setChoice] = useState<RetentionChoice>(savedChoice)
    const [draftMonths, setDraftMonths] = useState<number | null>(retentionMonths ?? defaultMonths)

    useEffect(() => {
        setChoice(savedChoice)
        setDraftMonths(retentionMonths ?? defaultMonths)
    }, [savedChoice, retentionMonths, defaultMonths])

    const draftValue = choice === 'custom' ? draftMonths : null
    const draftProblem = choice === 'custom' && draftMonths === null ? 'Choose a period' : null
    const saveDisabledReason =
        restrictionReason ?? draftProblem ?? (draftValue === retentionMonths ? 'No changes to save' : null)
    const countedMonths = draftValue ?? defaultMonths

    useEffect(() => {
        onCountImpact(countedMonths)
    }, [countedMonths, onCountImpact])

    const confirmDeletion = (months: number, description: string, onConfirm: () => void): void => {
        LemonDialog.open({
            title: `Keep events for ${retentionPeriodLabel(months)}?`,
            description,
            primaryButton: {
                children: 'Save',
                onClick: onConfirm,
                'data-attr': `${dataAttr}-confirm`,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const saveCustom = (months: number): void => {
        confirmDeletion(
            months,
            `${scope} will be kept for ${retentionPeriodLabel(months)}. Deletion of older events is not instant. It happens once a month, next on ${formatDate(nextMonthlyCleanupOn)}.`,
            () => onSave(months)
        )
    }

    const saveDefault = (): void => {
        if (!defaultDeletesMore(props)) {
            onSave(null)
            return
        }
        const deletesOn =
            monthlyDefaultMonths !== null ? nextMonthlyCleanupOn : passSchedule && nextPassOn(passSchedule)
        const period = retentionPeriodLabel(defaultMonths)
        confirmDeletion(
            defaultMonths,
            deletesOn
                ? `${scope} will be kept for the default of ${period}. Deletion of older events is not instant. The next deletion is on ${formatDate(deletesOn)}.`
                : `${scope} will be kept for the default of ${period}. Deletion of older events is not instant. It happens at least 3 months from now.`,
            () => onSave(null)
        )
    }

    const save = (): void => {
        if (saveDisabledReason) {
            return
        }
        if (draftValue === null) {
            saveDefault()
        } else {
            saveCustom(draftValue)
        }
    }

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
                options={retentionChoiceOptions(props)}
            />
            {choice === 'custom' && (
                <EventsRetentionCustomFields
                    months={draftMonths}
                    choiceMonths={choiceMonths}
                    planMonths={planMonths}
                    overrideNote={overrideNote}
                    disabledReason={restrictionReason ?? (saving ? 'Saving...' : null)}
                    onChange={setDraftMonths}
                    dataAttr={dataAttr}
                />
            )}
            <EventsRetentionImpactNote months={countedMonths} impact={impact} loading={impactLoading} />
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
