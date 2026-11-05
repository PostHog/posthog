import { IconCheckCircle, IconHide } from '@posthog/icons'
import { Button } from '@posthog/quill'

export function MockVerdictButtons({ labelled = false }: { labelled?: boolean }): JSX.Element {
    return (
        <>
            <Button
                variant="link-muted"
                size={labelled ? 'sm' : 'icon-sm'}
                aria-label="Resolve"
                tooltip={labelled ? undefined : 'Resolve'}
            >
                <IconCheckCircle className="size-3.5" />
                {labelled && 'Resolve'}
            </Button>
            <Button
                variant="link-muted"
                size={labelled ? 'sm' : 'icon-sm'}
                aria-label="Dismiss"
                tooltip={labelled ? undefined : 'Dismiss'}
            >
                <IconHide className="size-3.5" />
                {labelled && 'Dismiss'}
            </Button>
        </>
    )
}
