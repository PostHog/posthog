import { IconTrash } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

export function QuillPendingOAuthView({
    restrictedReason,
    onContinueOAuth,
    onCancelInstall,
}: {
    restrictedReason: string | null
    onContinueOAuth: () => void
    onCancelInstall: () => void
}): JSX.Element {
    return (
        <Empty className="rounded-md border border-dashed border-border">
            <EmptyHeader>
                <EmptyTitle>Finish connecting</EmptyTitle>
                <EmptyDescription>
                    This server hasn't completed its OAuth handshake yet. Click below to continue.
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <div className="flex flex-wrap items-center justify-center gap-2">
                    <Button variant="primary" onClick={onContinueOAuth} disabledReason={restrictedReason}>
                        Continue OAuth
                    </Button>
                    <Button variant="destructive-outline" onClick={onCancelInstall} disabledReason={restrictedReason}>
                        <IconTrash />
                        Cancel install
                    </Button>
                </div>
            </EmptyContent>
        </Empty>
    )
}
