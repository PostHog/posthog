import { useActions, useValues } from 'kea'

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
    FieldLegend,
    FieldSet,
    Label,
    RadioGroup,
    RadioGroupItem,
} from '@posthog/quill'

import { isDeprecatePayload, noReadsLabel, refreshCostLabel } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { REFRESH_CHOICES, RefreshChoice } from './DeprecateSuggestionModal'

const MATERIALIZATION_LEGEND = 'Its materialization'

export function QuillDeprecateSuggestionModal(): JSX.Element | null {
    const { acceptConfirmSuggestion, actionsInFlight, keepMaterialized, status } = useValues(warehouseSuggestionsLogic)
    const { confirmAccept, closeAcceptConfirm, setKeepMaterialized } = useActions(warehouseSuggestionsLogic)
    const payload = acceptConfirmSuggestion?.payload

    if (!acceptConfirmSuggestion || !payload || !isDeprecatePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[acceptConfirmSuggestion.id]

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && !inFlight && closeAcceptConfirm()}>
            <DialogContent size="wide" className="max-w-xl" showCloseButton={!inFlight}>
                <DialogHeader>
                    <DialogTitle>{`Mark ${payload.subject_name} as deprecated?`}</DialogTitle>
                    <DialogDescription>
                        {`${noReadsLabel(status?.window_days ?? 0)}. ${refreshCostLabel(payload)}.`}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldSet disabled={inFlight}>
                        <FieldLegend variant="label">{MATERIALIZATION_LEGEND}</FieldLegend>
                        <RadioGroup
                            aria-label={MATERIALIZATION_LEGEND}
                            value={keepMaterialized ? 'keep' : 'stop'}
                            onValueChange={(choice) => setKeepMaterialized((choice as RefreshChoice) === 'keep')}
                        >
                            {REFRESH_CHOICES.map((choice) => (
                                <Field key={choice.value} orientation="horizontal" className="items-start">
                                    <RadioGroupItem
                                        value={choice.value}
                                        id={`deprecate-refresh-${choice.value}`}
                                        data-attr={choice['data-attr']}
                                    />
                                    <FieldContent>
                                        <Label htmlFor={`deprecate-refresh-${choice.value}`}>{choice.label}</Label>
                                        <FieldDescription>{choice.description}</FieldDescription>
                                    </FieldContent>
                                </Field>
                            ))}
                        </RadioGroup>
                    </FieldSet>
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
                        variant="primary"
                        loading={inFlight}
                        onClick={() => confirmAccept()}
                        data-attr="warehouse-suggestions-deprecate-confirm"
                    >
                        Mark deprecated
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
