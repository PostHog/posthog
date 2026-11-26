import posthog from 'posthog-js'

import { IconCode } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { parseSourceFile } from './sourceFile'

/** The tag that marks an email your code sends. It opens the linked source file when there is one. */
export function CodeBadge({ sourceUrl }: { sourceUrl: string | null }): JSX.Element {
    const file = sourceUrl ? parseSourceFile(sourceUrl) : null
    const tag = (
        <LemonTag type="muted" size="small" icon={<IconCode />} className={file ? 'cursor-pointer' : undefined}>
            Code
        </LemonTag>
    )
    if (!file) {
        return <Tooltip title="Managed by code. The content comes with each send.">{tag}</Tooltip>
    }
    return (
        <Tooltip
            title={
                <>
                    Managed by code in <code>{file.path}</code>
                    {file.repo ? (
                        <>
                            {' '}
                            in <code>{file.repo}</code>
                        </>
                    ) : null}
                    . Click to open the file.
                </>
            }
        >
            <Link
                to={file.url}
                target="_blank"
                className="inline-flex"
                data-attr="code-email-source-file-link"
                onClick={(event) => {
                    // The tag sits inside the row's name link, so the click must not open the row too.
                    event.stopPropagation()
                    // pinned: analytics event name
                    posthog.capture('code email source file link clicked', { host: file.host })
                }}
            >
                {tag}
            </Link>
        </Tooltip>
    )
}
