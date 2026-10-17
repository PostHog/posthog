import { cn } from 'lib/utils/css-classes'

const OPEN_LINKS_IN_NEW_TAB = '<base target="_blank">'

export function withLinksInNewTab(html: string): string {
    const head = /<head(\s[^>]*)?>/i.exec(html)
    if (!head) {
        return OPEN_LINKS_IN_NEW_TAB + html
    }
    const afterHead = head.index + head[0].length
    return html.slice(0, afterHead) + OPEN_LINKS_IN_NEW_TAB + html.slice(afterHead)
}

export function EmailHtmlFrame({ html, className }: { html: string; className?: string }): JSX.Element {
    return (
        <iframe
            srcDoc={withLinksInNewTab(html)}
            sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
            title="Message template preview"
            className={cn('w-full border-0 bg-white', className)}
        />
    )
}
