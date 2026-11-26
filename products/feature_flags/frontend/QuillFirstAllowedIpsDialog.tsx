import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { featureFlagRequestListsLogic } from './featureFlagRequestListsLogic'
import { FIRST_ALLOWED_IPS_COPY } from './firstAllowedIpsCopy'

export function QuillFirstAllowedIpsDialog(): JSX.Element {
    const { firstAllowedIps } = useValues(featureFlagRequestListsLogic)
    const { cancelFirstAllowedIps, confirmFirstAllowedIps } = useActions(featureFlagRequestListsLogic)

    return (
        <AlertDialog open={!!firstAllowedIps} onOpenChange={(open: boolean) => !open && cancelFirstAllowedIps()}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{FIRST_ALLOWED_IPS_COPY.title}</AlertDialogTitle>
                    <AlertDialogDescription>{FIRST_ALLOWED_IPS_COPY.description}</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>
                        {FIRST_ALLOWED_IPS_COPY.cancel}
                    </AlertDialogClose>
                    <Button
                        variant="destructive-outline"
                        onClick={() => firstAllowedIps && confirmFirstAllowedIps(firstAllowedIps)}
                        data-attr="feature-flag-allowed-ips-confirm"
                    >
                        {FIRST_ALLOWED_IPS_COPY.confirm}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
