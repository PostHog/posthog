import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@posthog/quill'

/** A dialog on every screen size, because the answers table needs the width. */
export const QuillContentAutopilotCitationsModal = ({
    open,
    title,
    description,
    onClose,
    children,
}: {
    open: boolean
    title: string
    description: string | undefined
    onClose: () => void
    children: React.ReactNode
}): JSX.Element => (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
        <DialogContent size="wide">
            <DialogHeader>
                <DialogTitle>{title}</DialogTitle>
                {description ? <DialogDescription>{description}</DialogDescription> : null}
            </DialogHeader>
            <DialogBody>{children}</DialogBody>
        </DialogContent>
    </Dialog>
)
