import { useMemo } from 'react'

import { cn } from 'lib/utils/css-classes'

function doctypeOf(parsed: Document): string {
    return parsed.doctype ? new XMLSerializer().serializeToString(parsed.doctype) : ''
}

function withLinksInNewTab(html: string): string {
    const parsed = new DOMParser().parseFromString(html, 'text/html')
    for (const link of parsed.querySelectorAll('a[href], area[href]')) {
        link.setAttribute('target', '_blank')
    }
    return doctypeOf(parsed) + parsed.documentElement.outerHTML
}

export function EmailHtmlFrame({ html, className }: { html: string; className?: string }): JSX.Element {
    const previewDocument = useMemo(() => withLinksInNewTab(html), [html])
    return (
        <iframe
            srcDoc={previewDocument}
            sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
            title="Message template preview"
            className={cn('w-full border-0 bg-white', className)}
        />
    )
}
