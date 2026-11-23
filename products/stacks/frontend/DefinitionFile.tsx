import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import type { DefinitionSourceRefApi } from './generated/api.schemas'
import { definitionFileUrl } from './managedInCode'

export interface DefinitionFileProps {
    repository: string
    source: DefinitionSourceRefApi
    kind: string
}

/** The definition's file, as a link to GitHub when the repository is a GitHub `owner/name`. */
export function DefinitionFile({ repository, source, kind }: DefinitionFileProps): JSX.Element {
    const url = definitionFileUrl(repository, source)
    const name = <code>{source.file}</code>
    if (!url) {
        return name
    }
    return (
        <Link
            to={url}
            target="_blank"
            data-attr="managed-in-code-definition-file"
            // pinned: analytics event name, renaming breaks dashboards
            onClick={() => posthog.capture('managed in code file opened', { kind })}
        >
            {name}
        </Link>
    )
}
