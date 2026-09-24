import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { isCodeManagedWorkflow, workflowSource } from './codeManagedWorkflow'
import { HogFlow } from './hogflows/types'

function SourcePart({ label, url }: { label: string; url: string | undefined }): JSX.Element {
    return url ? (
        <Link to={url} target="_blank" className="font-mono break-words">
            {label}
        </Link>
    ) : (
        <span className="font-mono break-words">{label}</span>
    )
}

/**
 * One line that says where a code-managed workflow comes from: the file, the repository and the ref
 * of the last push. Each part is linked when the host is one we can link, and left out when the row
 * does not record it. Renders nothing for a workflow this app owns.
 */
export function CodeManagedSource({
    workflow,
    className,
}: {
    workflow: HogFlow | null | undefined
    className?: string
}): JSX.Element | null {
    if (!isCodeManagedWorkflow(workflow)) {
        return null
    }
    const { path, fileUrl, repository, repositoryUrl, ref, refUrl } = workflowSource(workflow)
    if (!path && !repository && !ref) {
        return null
    }

    return (
        <p className={cn('m-0 text-sm text-secondary min-w-0', className)} data-attr="workflow-code-source">
            {path && <SourcePart label={path} url={fileUrl} />}
            {path && repository && ' in '}
            {repository && <SourcePart label={repository} url={repositoryUrl} />}
            {ref && (
                <>
                    {path || repository ? ', last pushed from ' : 'Last pushed from '}
                    <SourcePart label={ref} url={refUrl} />
                </>
            )}
        </p>
    )
}
