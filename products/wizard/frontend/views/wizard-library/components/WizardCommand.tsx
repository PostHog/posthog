import { IconCheck } from '@posthog/icons'
import { Button, Card, CardContent, CardHeader, Text } from '@posthog/quill-primitives'

export function WizardCommand({
    command,
    showCopyButton,
    copied,
    onCopy,
}: {
    command: string
    showCopyButton: boolean
    copied: boolean
    onCopy: () => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Card className="bg-muted">
                {!showCopyButton && (
                    <CardHeader className="justify-end">
                        <Button size="sm" variant="outline" onClick={onCopy}>
                            Copy command
                        </Button>
                    </CardHeader>
                )}
                <CardContent>
                    <code className="block overflow-x-auto whitespace-pre-wrap break-words font-mono text-xs">
                        {command}
                    </code>
                </CardContent>
            </Card>
            {showCopyButton && (
                <Button variant="outline" onClick={onCopy}>
                    Copy command
                </Button>
            )}
            {copied && (
                <Text size="sm" className="flex items-center gap-1 text-success-foreground">
                    <IconCheck /> Command copied.
                </Text>
            )}
        </div>
    )
}
