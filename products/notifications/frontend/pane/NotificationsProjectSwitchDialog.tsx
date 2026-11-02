import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { notificationsPaneLogic } from './notificationsPaneLogic'

/** Opening a notification from another project reloads the app in that project, so it asks first. */
export function NotificationsProjectSwitchDialog(): JSX.Element | null {
    const { pendingProjectSwitch } = useValues(notificationsPaneLogic)
    const { setPendingProjectSwitch, confirmProjectSwitch } = useActions(notificationsPaneLogic)
    const [switching, setSwitching] = useState(false)
    if (!pendingProjectSwitch) {
        return null
    }
    const projectName = pendingProjectSwitch.projectName ?? 'another project'
    return (
        <AlertDialog
            open
            onOpenChange={(open: boolean) => {
                if (!open && !switching) {
                    setPendingProjectSwitch(null)
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Switch to {projectName}?</AlertDialogTitle>
                    <AlertDialogDescription>
                        This notification is in {projectName}. Opening it reloads the page, and anything you haven't
                        saved is lost.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => setPendingProjectSwitch(null)}
                        disabled={switching}
                        data-attr="notifications-pane-switch-cancel"
                    >
                        Stay here
                    </Button>
                    <Button
                        variant="primary"
                        loading={switching}
                        onClick={() => {
                            setSwitching(true)
                            confirmProjectSwitch()
                        }}
                        data-attr="notifications-pane-switch-confirm"
                    >
                        Switch project
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
