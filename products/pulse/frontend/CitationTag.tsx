import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'

import { BriefCitation, CITATION_TYPES } from './pulseLogic'

export function CitationTag({ citation }: { citation: BriefCitation }): JSX.Element {
    const { type, ref } = citation
    const citationType = ref ? CITATION_TYPES[type] : undefined
    const url = citationType?.url(ref)

    if (citationType && url) {
        return (
            <Link to={url}>
                <LemonTag>{citationType.hideRef ? citationType.label : `${citationType.label} ${ref}`}</LemonTag>
            </Link>
        )
    }
    return <LemonTag>{type ? `${type}:${ref}` : ref}</LemonTag>
}
