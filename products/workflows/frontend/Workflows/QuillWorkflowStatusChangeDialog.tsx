import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Text,
} from '@posthog/quill'

import type { HogFlow } from './hogflows/types'
import {
    STATUS_CHANGE_CANCEL_ATTR,
    STATUS_CHANGE_CONFIRM_ATTR,
    WorkflowStatusChangeTarget,
    statusChangeConsequence,
    statusChangeTitle,
    triggerRecap,
} from './workflowStatusChange'

export function QuillWorkflowStatusChangeDialog({
    open,
    status,
    trigger,
    onClose,
    onConfirm,
}: {
    open: boolean
    status: WorkflowStatusChangeTarget
    trigger: HogFlow['trigger']
    onClose: () => void
    onConfirm: (status: WorkflowStatusChangeTarget) => void
}): JSX.Element {
    return (
        <AlertDialog
            open={open}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{statusChangeTitle(status)}</AlertDialogTitle>
                    <AlertDialogDescription>{statusChangeConsequence(status)}</AlertDialogDescription>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        <strong>Trigger:</strong> {triggerRecap(trigger)}
                    </Text>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" data-attr={STATUS_CHANGE_CANCEL_ATTR} />}>
                        Actually no
                    </AlertDialogClose>
                    <Button
                        variant={status === 'active' ? 'primary' : 'destructive-outline'}
                        onClick={() => {
                            onClose()
                            onConfirm(status)
                        }}
                        data-attr={STATUS_CHANGE_CONFIRM_ATTR[status]}
                    >
                        Yes, continue
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
