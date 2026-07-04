import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'

import { BriefCitation, CITATION_TYPES } from './pulseLogic'

export function CitationTag({ citation }: { citation: BriefCitation }): JSX.Element {
    const { type, ref } = citation
    const citationType = ref ? CITATION_TYPES[type] : undefined

    if (citationType) {
        const tag = <LemonTag>{citationType.hideRef ? citationType.label : `${citationType.label} ${ref}`}</LemonTag>
        const url = citationType.url(ref)
        // Known types without a URL (e.g. query findings shown on the same page) render the
        // labeled tag, unlinked.
        return url ? <Link to={url}>{tag}</Link> : tag
    }
    return <LemonTag>{type ? `${type}:${ref}` : ref}</LemonTag>
}
