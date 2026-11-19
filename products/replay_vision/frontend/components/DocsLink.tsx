import { Link } from '@posthog/lemon-ui'

// Keep utm-free: ProductIntroduction appends its own utm params to docsURL.
const VISION_DOCS_URL = 'https://posthog.com/docs/replay-vision'

export type VisionDocsPage =
    | 'creating-scanners'
    | 'running-scanners'
    | 'observations'
    | 'quota-and-limits'
    | 'actions'
    | 'webhooks'
    | 'what-to-watch'

/** Raw docs URL for surfaces that need an href instead of a link, like ProductIntroduction's docsURL prop. */
export function visionDocsUrl(page?: VisionDocsPage): string {
    return `${VISION_DOCS_URL}${page ? `/${page}` : ''}`
}

/** Docs link for replay vision surfaces. Opens in a new tab so the user keeps their place in the app. */
export function VisionDocsLink({
    page,
    anchor,
    dataAttr,
    onClick,
    children,
}: {
    page?: VisionDocsPage
    anchor?: string
    dataAttr: string
    onClick?: () => void
    children: React.ReactNode
}): JSX.Element {
    return (
        <Link
            to={`${visionDocsUrl(page)}?utm_medium=in-product&utm_campaign=empty-state-docs-link${anchor ? `#${anchor}` : ''}`}
            target="_blank"
            onClick={onClick}
            data-attr={dataAttr}
        >
            {children}
        </Link>
    )
}
