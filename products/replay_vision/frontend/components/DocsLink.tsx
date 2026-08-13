import { Link } from '@posthog/lemon-ui'

export const VISION_DOCS_URL = 'https://posthog.com/docs/replay-vision'

/** Docs link for empty states. Opens in a new tab so the user keeps their place in the app. */
export function VisionDocsLink({
    page,
    dataAttr,
    children,
}: {
    page?: string
    dataAttr: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <Link
            to={`${VISION_DOCS_URL}${page ? `/${page}` : ''}?utm_medium=in-product&utm_campaign=empty-state-docs-link`}
            target="_blank"
            data-attr={dataAttr}
        >
            {children}
        </Link>
    )
}
