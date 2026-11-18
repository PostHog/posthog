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
    FieldGroup,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { QuillExperimentFlagKeyInput } from 'scenes/experiments/QuillExperimentFlagKeyInput'

import { Experiment } from '~/types'

import {
    COPY_EXPERIMENT_DESCRIPTION,
    COPY_EXPERIMENT_TITLE,
    DUPLICATE_EXPERIMENT_TITLE,
    SELECT_PROJECT_REASON,
    copyNamePlaceholder,
    useCopyExperimentToProjectModal,
    useDuplicateExperimentModal,
} from './experimentCopyModals'

interface CopyModalProps {
    isOpen: boolean
    onClose: () => void
    experiment: Experiment
}

export function QuillDuplicateExperimentModal({ isOpen, onClose, experiment }: CopyModalProps): JSX.Element {
    const { experimentName, handleNameChange, handleDuplicate, handleClose, flagKeyInputProps } =
        useDuplicateExperimentModal(experiment, onClose)

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && handleClose()}>
            <DialogContent size="wide" className="max-w-2xl" data-attr="duplicate-experiment-modal">
                <DialogHeader>
                    <DialogTitle>{DUPLICATE_EXPERIMENT_TITLE}</DialogTitle>
                    <DialogDescription>
                        Create a new experiment using the configuration from <strong>{experiment.name}</strong>.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel htmlFor="duplicate-experiment-name">Experiment name</FieldLabel>
                            <Input
                                id="duplicate-experiment-name"
                                value={experimentName}
                                onChange={(event) => handleNameChange(event.target.value)}
                                placeholder={copyNamePlaceholder(experiment)}
                                autoFocus
                                data-attr="duplicate-experiment-name"
                            />
                        </Field>
                        <QuillExperimentFlagKeyInput {...flagKeyInputProps} />
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={handleClose}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={handleDuplicate} data-attr="duplicate-experiment-submit">
                        Duplicate
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

export function QuillCopyExperimentToProjectModal({ isOpen, onClose, experiment }: CopyModalProps): JSX.Element {
    const {
        teamOptions,
        selectedTeamId,
        handleTeamChange,
        experimentName,
        handleNameChange,
        handleCopy,
        handleClose,
        copying,
        flagKeyInputProps,
    } = useCopyExperimentToProjectModal({ isOpen, onClose, experiment })

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && handleClose()}>
            <DialogContent size="wide" className="max-w-2xl" data-attr="copy-experiment-to-project-modal">
                <DialogHeader>
                    <DialogTitle>{COPY_EXPERIMENT_TITLE}</DialogTitle>
                    <DialogDescription>{COPY_EXPERIMENT_DESCRIPTION}</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel>Destination project</FieldLabel>
                            <Select
                                value={selectedTeamId === null ? null : String(selectedTeamId)}
                                onValueChange={(next: string | null) => handleTeamChange(next ? Number(next) : null)}
                            >
                                <SelectTrigger className="w-full" data-attr="copy-experiment-project">
                                    <SelectValue>
                                        {(current: string | null) =>
                                            teamOptions.find((option) => String(option.value) === current)?.label ??
                                            SELECT_PROJECT_REASON
                                        }
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    {teamOptions.map((option) => (
                                        <SelectItem key={option.value} value={String(option.value)}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>
                        {selectedTeamId && (
                            <>
                                <Field>
                                    <FieldLabel htmlFor="copy-experiment-name">Experiment name</FieldLabel>
                                    <Input
                                        id="copy-experiment-name"
                                        value={experimentName}
                                        onChange={(event) => handleNameChange(event.target.value)}
                                        placeholder={copyNamePlaceholder(experiment)}
                                        data-attr="copy-experiment-name"
                                    />
                                </Field>
                                <QuillExperimentFlagKeyInput {...flagKeyInputProps} />
                            </>
                        )}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={handleClose}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={handleCopy}
                        loading={copying}
                        disabledReason={!selectedTeamId ? SELECT_PROJECT_REASON : undefined}
                    >
                        Copy
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
