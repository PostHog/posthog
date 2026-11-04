import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldGroup,
    FieldLegend,
    FieldSet,
    Label,
    RadioGroup,
    RadioGroupItem,
} from '@posthog/quill'

import { deleteDisabledReason, isDeprecatePayload, noReadsLabel, refreshCostLabel } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { ACTION_CHOICES, ActionChoice, REFRESH_CHOICES, RefreshChoice } from './DeprecateSuggestionModal'

interface QuillChoice<T extends string> {
    value: T
    label: ReactNode
    description?: ReactNode
    disabledReason?: string
    'data-attr'?: string
}

const ACTION_LEGEND = 'What to do'
const MATERIALIZATION_LEGEND = 'Its materialization'

function QuillChoiceGroup<T extends string>({
    legend,
    idPrefix,
    value,
    onChange,
    choices,
    disabled,
}: {
    legend: string
    idPrefix: string
    value: T
    onChange: (value: T) => void
    choices: QuillChoice<T>[]
    disabled: boolean
}): JSX.Element {
    return (
        <FieldSet disabled={disabled}>
            <FieldLegend variant="label">{legend}</FieldLegend>
            <RadioGroup aria-label={legend} value={value} onValueChange={(choice) => onChange(choice as T)}>
                {choices.map((choice) => (
                    <Field key={choice.value} orientation="horizontal" className="items-start">
                        <RadioGroupItem
                            value={choice.value}
                            id={`${idPrefix}-${choice.value}`}
                            disabled={!!choice.disabledReason}
                            data-attr={choice['data-attr']}
                        />
                        <FieldContent>
                            <Label htmlFor={`${idPrefix}-${choice.value}`}>{choice.label}</Label>
                            <FieldDescription>{choice.description}</FieldDescription>
                            {choice.disabledReason && <FieldDescription>{choice.disabledReason}</FieldDescription>}
                        </FieldContent>
                    </Field>
                ))}
            </RadioGroup>
        </FieldSet>
    )
}

export function QuillDeprecateSuggestionModal(): JSX.Element | null {
    const { acceptConfirmSuggestion, actionsInFlight, deleteView, keepMaterialized, status } =
        useValues(warehouseSuggestionsLogic)
    const { confirmAccept, closeAcceptConfirm, setDeleteView, setKeepMaterialized } =
        useActions(warehouseSuggestionsLogic)
    const payload = acceptConfirmSuggestion?.payload

    if (!acceptConfirmSuggestion || !payload || !isDeprecatePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[acceptConfirmSuggestion.id]
    const materialized = payload.materialized !== false
    const windowDays = status?.window_days ?? 0
    const noReads = noReadsLabel(windowDays)
    const deleteBlockedReason = deleteDisabledReason(acceptConfirmSuggestion.evidence, windowDays)
    const actionChoices = ACTION_CHOICES.map((choice) =>
        choice.value === 'delete' ? { ...choice, disabledReason: deleteBlockedReason } : choice
    )

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && !inFlight && closeAcceptConfirm()}>
            <DialogContent size="wide" className="max-w-xl" showCloseButton={!inFlight}>
                <DialogHeader>
                    <DialogTitle>
                        {deleteView ? `Delete ${payload.subject_name}?` : `Mark ${payload.subject_name} as deprecated?`}
                    </DialogTitle>
                    <DialogDescription>
                        {materialized ? `${noReads}. ${refreshCostLabel(payload)}.` : `${noReads}.`}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <QuillChoiceGroup<ActionChoice>
                            legend={ACTION_LEGEND}
                            idPrefix="deprecate-action"
                            value={deleteView ? 'delete' : 'deprecate'}
                            onChange={(choice) => setDeleteView(choice === 'delete')}
                            choices={actionChoices}
                            disabled={inFlight}
                        />
                        {materialized && !deleteView && (
                            <QuillChoiceGroup<RefreshChoice>
                                legend={MATERIALIZATION_LEGEND}
                                idPrefix="deprecate-refresh"
                                value={keepMaterialized ? 'keep' : 'stop'}
                                onChange={(choice) => setKeepMaterialized(choice === 'keep')}
                                choices={REFRESH_CHOICES}
                                disabled={inFlight}
                            />
                        )}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeAcceptConfirm}
                        disabledReason={inFlight ? 'Working' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant={deleteView ? 'destructive' : 'primary'}
                        loading={inFlight}
                        onClick={() => confirmAccept()}
                        data-attr={
                            deleteView
                                ? 'warehouse-suggestions-delete-confirm'
                                : 'warehouse-suggestions-deprecate-confirm'
                        }
                    >
                        {deleteView ? 'Delete view' : 'Mark deprecated'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
