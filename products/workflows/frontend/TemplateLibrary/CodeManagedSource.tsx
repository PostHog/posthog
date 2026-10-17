import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { TemplateSource } from './codeManagedTemplate'

function SourcePart({ label, url }: { label: string; url: string | undefined }): JSX.Element {
    return url ? (
        <Link to={url} target="_blank" className="font-mono break-all">
            {label}
        </Link>
    ) : (
        <span className="font-mono break-all">{label}</span>
    )
}

export function CodeManagedSource({
    source,
    className,
}: {
    source: TemplateSource | null
    className?: string
}): JSX.Element | null {
    if (!source) {
        return null
    }
    const { path, fileUrl, repository, repositoryUrl, ref, refUrl } = source

    return (
        <p className={cn('m-0 text-sm text-secondary min-w-0', className)} data-attr="message-template-code-source">
            {path && <SourcePart label={path} url={fileUrl} />}
            {path && repository && <span> in </span>}
            {repository && <SourcePart label={repository} url={repositoryUrl} />}
            {ref && (
                <>
                    <span>{path || repository ? ', last uploaded from ' : 'Last uploaded from '}</span>
                    <SourcePart label={ref} url={refUrl} />
                </>
            )}
        </p>
    )
}
