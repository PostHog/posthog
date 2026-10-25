import { useId, useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Text,
    Textarea,
} from '@posthog/quill-primitives'

import type { TurnFeedbackDialogProps } from '../TurnFeedbackDialog'

/** Quill skin of `TurnFeedbackDialog`. */
export function QuillTurnFeedbackDialog({ isOpen, onClose }: TurnFeedbackDialogProps): JSX.Element {
    const [feedback, setFeedback] = useState('')
    const textAreaId = useId()

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                // Esc, the backdrop, the X button and Cancel all close through here. Submit closes through props.
                if (!open) {
                    onClose('cancelled', feedback)
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Share feedback</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <Field>
                        <FieldLabel htmlFor={textAreaId}>
                            What disappointed you about the answer?
                            <Text size="xs" variant="muted" render={<span />}>
                                (optional)
                            </Text>
                        </FieldLabel>
                        <Textarea
                            id={textAreaId}
                            placeholder="Help us improve PostHog AI…"
                            value={feedback}
                            onChange={(event) => setFeedback(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                                    event.preventDefault()
                                    onClose('submitted', feedback)
                                }
                            }}
                            rows={3}
                            autoFocus
                        />
                    </Field>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" data-attr="posthog-ai-turn-feedback-cancel" />}>
                        Cancel
                    </DialogClose>
                    <Button
                        variant="primary"
                        data-attr="posthog-ai-turn-feedback-submit"
                        onClick={() => onClose('submitted', feedback)}
                    >
                        Submit
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
