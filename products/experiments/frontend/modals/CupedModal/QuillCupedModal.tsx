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
    FieldDescription,
    FieldGroup,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { CupedSelection } from 'scenes/experiments/ExperimentView/cuped'

import { MAX_LOOKBACK_DAYS, MIN_LOOKBACK_DAYS } from 'products/experiments/frontend/constants'
import { teamDefaultOptions } from 'products/experiments/frontend/modals/StatsMethodModal/useStatsMethodModal'

import { CUPED_HELP, CUPED_LOOKBACK_HELP, CupedModalModel } from './useCupedModal'

export function QuillCupedModal({ model }: { model: CupedModalModel }): JSX.Element {
    const {
        experiment,
        experimentUpdateLoading,
        updateExperimentSettings,
        isCupedModalOpen,
        savingReason,
        selection,
        teamDefaultEnabled,
        lookbackDays,
        onClose,
        updateSelection,
        updateLookbackDays,
    } = model
    const options = teamDefaultOptions(teamDefaultEnabled)

    return (
        <Dialog
            open={isCupedModalOpen}
            onOpenChange={(open: boolean) => {
                // Cancel does not stop a running save. The save still applies, and its response replaces any new edit.
                if (!open && !experimentUpdateLoading) {
                    onClose()
                }
            }}
        >
            <DialogContent data-attr="experiment-cuped-modal">
                <DialogHeader>
                    <DialogTitle>CUPED variance reduction</DialogTitle>
                    <DialogDescription>{CUPED_HELP}</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel>CUPED</FieldLabel>
                            <Select
                                value={selection}
                                disabled={!!savingReason}
                                onValueChange={(value) => value && updateSelection(value as CupedSelection)}
                            >
                                <SelectTrigger>
                                    <SelectValue>
                                        {(value: string) =>
                                            options.find((option) => option.value === value)?.label ?? value
                                        }
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    {options.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>
                        {selection === 'enabled' && (
                            <Field>
                                <FieldLabel htmlFor="cuped-lookback-days">Lookback window (days)</FieldLabel>
                                <Input
                                    id="cuped-lookback-days"
                                    type="number"
                                    min={MIN_LOOKBACK_DAYS}
                                    max={MAX_LOOKBACK_DAYS}
                                    value={lookbackDays}
                                    disabled={!!savingReason}
                                    className="w-32"
                                    onChange={(event) => {
                                        const value = Number(event.target.value)
                                        if (!Number.isFinite(value)) {
                                            return
                                        }
                                        const rounded = Math.round(value)
                                        if (rounded < MIN_LOOKBACK_DAYS || rounded > MAX_LOOKBACK_DAYS) {
                                            return
                                        }
                                        updateLookbackDays(rounded)
                                    }}
                                />
                                <FieldDescription>{CUPED_LOOKBACK_HELP}</FieldDescription>
                            </Field>
                        )}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose} disabledReason={savingReason}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={experimentUpdateLoading}
                        onClick={() => updateExperimentSettings({ stats_config: experiment.stats_config }, 'cuped')}
                    >
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
