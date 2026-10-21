import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from 'lib/ui/quill'

export function ConnectGitHubToFixModal({
    open,
    onOpenChange,
    connectUrl,
    onConnect,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    connectUrl: string
    onConnect: () => void
}): JSX.Element {
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Connect GitHub to fix this issue</DialogTitle>
                    <DialogDescription>
                        Connect GitHub to this project so PostHog AI can work on your code and open a draft pull
                        request. After connecting, select Fix again.
                    </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        nativeButton={false}
                        render={<LinkPrimitive to={connectUrl} disableClientSideRouting />}
                        onClick={onConnect}
                        data-attr="error-tracking-fix-connect-github"
                    >
                        Connect GitHub
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
