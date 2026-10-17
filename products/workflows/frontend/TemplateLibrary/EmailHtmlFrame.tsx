import { cn } from 'lib/utils/css-classes'

export function EmailHtmlFrame({ html, className }: { html: string; className?: string }): JSX.Element {
    return (
        <iframe
            srcDoc={html}
            sandbox="allow-same-origin"
            title="Message template preview"
            className={cn('w-full border-0 bg-white', className)}
        />
    )
}
