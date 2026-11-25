import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
} from '@posthog/quill'

import type { ContentAutopilotProfileDraft } from './contentAutopilotLogic'
import { ContentAutopilotSiteFields } from './ContentAutopilotSiteFields'
import { ContentAutopilotSourceFields } from './ContentAutopilotSourceFields'

/** The site's own settings on the settings page, with a confirmation before the site is deleted. */
export const QuillContentAutopilotSiteSettingsCard = ({
    siteLabel,
    draft,
    deleting,
    saving,
    saveDisabledReason,
    onDelete,
    onSave,
}: {
    siteLabel: string | null
    draft: ContentAutopilotProfileDraft
    deleting: boolean
    saving: boolean
    saveDisabledReason: string | undefined
    onDelete: () => void
    onSave: () => void
}): JSX.Element => {
    const [confirmOpen, setConfirmOpen] = useState(false)

    return (
        <Card className="w-full max-w-3xl">
            <CardHeader>
                <CardDescription>Change this site's sources and research boundaries.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
                <ContentAutopilotSiteFields draft={draft} />
                <ContentAutopilotSourceFields draft={draft} />
            </CardContent>
            <CardFooter className="justify-between gap-2">
                <Button
                    variant="destructive-outline"
                    onClick={() => siteLabel !== null && setConfirmOpen(true)}
                    loading={deleting}
                    data-attr="content-autopilot-delete-site"
                >
                    <IconTrash />
                    Delete site
                </Button>
                <Button variant="primary" onClick={onSave} loading={saving} disabledReason={saveDisabledReason}>
                    Save settings
                </Button>
            </CardFooter>
            <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Delete {siteLabel}?</AlertDialogTitle>
                        <AlertDialogDescription>
                            PostHog stops any run in progress and removes this site and its proposals from the
                            workspace. You can add the site again later.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <Button variant="outline" onClick={() => setConfirmOpen(false)}>
                            Keep site
                        </Button>
                        <Button
                            variant="destructive-outline"
                            onClick={() => {
                                setConfirmOpen(false)
                                onDelete()
                            }}
                        >
                            Delete site
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </Card>
    )
}
