import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    FieldLegend,
    FieldSet,
    Input,
    Label,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { MAX_SEQUENTIAL_TUNING_PARAMETER, SequentialSelection } from 'scenes/experiments/ExperimentView/sequential'

import { ExperimentStatsMethod } from '~/types'

import { STATS_METHOD_OPTIONS } from 'products/experiments/frontend/components/StatsMethodSelector'
import { CONFIDENCE_LEVEL_OPTIONS } from 'products/experiments/frontend/constants'

import {
    SEQUENTIAL_TESTING_HELP,
    StatsMethodModalModel,
    TUNING_PARAMETER_HELP,
    confidenceHelp,
    teamDefaultOptions,
} from './useStatsMethodModal'

export function QuillStatsMethodModal({ model }: { model: StatsMethodModalModel }): JSX.Element {
    const {
        experiment,
        statsMethod,
        experimentUpdateLoading,
        setExperiment,
        updateExperimentSettings,
        isStatsEngineModalOpen,
        savingReason,
        onClose,
        isBayesian,
        currentConfidenceLevel,
        handleConfidenceLevelChange,
        sequentialSelection,
        teamDefaultSequentialEnabled,
        sequentialTuningParameter,
        updateSequentialSelection,
        updateSequentialTuningParameter,
    } = model
    const sequentialOptions = teamDefaultOptions(teamDefaultSequentialEnabled)

    return (
        <Dialog
            open={isStatsEngineModalOpen}
            onOpenChange={(open: boolean) => {
                // Cancel does not stop a running save. The save still applies, and its response replaces any new edit.
                if (!open && !experimentUpdateLoading) {
                    onClose()
                }
            }}
        >
            <DialogContent data-attr="experiment-stats-method-modal">
                <DialogHeader>
                    <DialogTitle>Statistics configuration</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <FieldSet>
                            <FieldLegend variant="label">Statistical method</FieldLegend>
                            <RadioGroup
                                value={statsMethod}
                                disabled={experimentUpdateLoading}
                                onValueChange={(method) =>
                                    setExperiment({
                                        stats_config: {
                                            ...experiment.stats_config,
                                            method: method as ExperimentStatsMethod,
                                        },
                                    })
                                }
                            >
                                {STATS_METHOD_OPTIONS.map((option) => (
                                    <Field key={option.value} orientation="horizontal" className="items-start">
                                        <RadioGroupItem
                                            value={option.value}
                                            id={`stats-method-${option.value}`}
                                            data-attr={`stats-method-${option.value}`}
                                        />
                                        <FieldContent>
                                            <Label htmlFor={`stats-method-${option.value}`}>{option.title}</Label>
                                            <FieldDescription>{option.description}</FieldDescription>
                                        </FieldContent>
                                    </Field>
                                ))}
                            </RadioGroup>
                        </FieldSet>
                        <Field>
                            <FieldLabel>Confidence level</FieldLabel>
                            <Select
                                value={String(currentConfidenceLevel)}
                                disabled={!!savingReason}
                                onValueChange={(value) => value && handleConfidenceLevelChange(Number(value))}
                            >
                                <SelectTrigger className="w-28">
                                    <SelectValue>
                                        {(value: string) =>
                                            CONFIDENCE_LEVEL_OPTIONS.find((option) => String(option.value) === value)
                                                ?.label ?? value
                                        }
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    {CONFIDENCE_LEVEL_OPTIONS.map((option) => (
                                        <SelectItem key={option.value} value={String(option.value)}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <FieldDescription>{confidenceHelp(isBayesian, currentConfidenceLevel)}</FieldDescription>
                        </Field>
                        {!isBayesian && (
                            <Field>
                                <FieldLabel>Sequential testing</FieldLabel>
                                <Select
                                    value={sequentialSelection}
                                    disabled={!!savingReason}
                                    onValueChange={(value) =>
                                        value && updateSequentialSelection(value as SequentialSelection)
                                    }
                                >
                                    <SelectTrigger className="w-72">
                                        <SelectValue>
                                            {(value: string) =>
                                                sequentialOptions.find((option) => option.value === value)?.label ??
                                                value
                                            }
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        {sequentialOptions.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                <FieldDescription>{SEQUENTIAL_TESTING_HELP}</FieldDescription>
                            </Field>
                        )}
                        {!isBayesian && sequentialSelection === 'enabled' && (
                            <Field>
                                <FieldLabel htmlFor="stats-tuning-parameter">Tuning parameter</FieldLabel>
                                <Input
                                    id="stats-tuning-parameter"
                                    type="number"
                                    min={1}
                                    max={MAX_SEQUENTIAL_TUNING_PARAMETER}
                                    value={sequentialTuningParameter}
                                    disabled={!!savingReason}
                                    className="w-32"
                                    onChange={(event) => {
                                        const value = Number(event.target.value)
                                        if (
                                            !Number.isFinite(value) ||
                                            value < 1 ||
                                            value > MAX_SEQUENTIAL_TUNING_PARAMETER
                                        ) {
                                            return
                                        }
                                        updateSequentialTuningParameter(Math.round(value))
                                    }}
                                />
                                <FieldDescription>{TUNING_PARAMETER_HELP}</FieldDescription>
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
                        onClick={() =>
                            updateExperimentSettings({ stats_config: experiment.stats_config }, 'statsMethod')
                        }
                    >
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
