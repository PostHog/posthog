import { useActions, useValues } from 'kea'
import { ChangeEvent, KeyboardEvent } from 'react'

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
    FieldError,
    FieldLabel,
    Input,
} from '@posthog/quill'

import { NEW_SPACE_NAME_MAX_LENGTH, newSpaceLogic } from './newSpaceLogic'

export function NewSpaceDialog(): JSX.Element {
    const { isOpen, name, nameError, submitting } = useValues(newSpaceLogic)
    const { closeNewSpace, setName, submitNewSpace } = useActions(newSpaceLogic)

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                if (!open && !submitting) {
                    closeNewSpace()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>New space</DialogTitle>
                    <DialogDescription>
                        A space keeps related sessions together. Everyone in this project can find it.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <Field data-invalid={!!nameError}>
                        <FieldLabel htmlFor="today-new-space-name">Name</FieldLabel>
                        <Input
                            id="today-new-space-name"
                            autoFocus
                            placeholder="e.g. mobile"
                            value={name}
                            maxLength={NEW_SPACE_NAME_MAX_LENGTH}
                            aria-invalid={!!nameError}
                            onChange={(event: ChangeEvent<HTMLInputElement>) => setName(event.target.value)}
                            onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                                if (event.key === 'Enter') {
                                    event.preventDefault()
                                    submitNewSpace()
                                }
                            }}
                            data-attr="today-new-space-name"
                        />
                        {nameError ? (
                            <FieldError>{nameError}</FieldError>
                        ) : (
                            <FieldDescription>Use lowercase letters, numbers, and hyphens.</FieldDescription>
                        )}
                    </Field>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeNewSpace}
                        disabled={submitting}
                        data-attr="today-new-space-cancel"
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={submitting}
                        onClick={submitNewSpace}
                        data-attr="today-new-space-create"
                    >
                        Create space
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
