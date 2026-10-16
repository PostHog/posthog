import type { SignalReportArtefact } from '../../types'
import { parsePrUrlParts } from '../../utils/reportPresentation'
import {
    artefactTypeLabel,
    ImplementationDecisionContent,
    ImplementationHandoverContent,
    ImplementationReplacementContent,
} from './artefactTypes'

function prReference(url: string): string {
    const pr = parsePrUrlParts(url)
    return pr ? `PR #${pr.number}` : 'Pull request'
}

export function prActivityTitle(artefact: SignalReportArtefact): string {
    switch (artefact.type) {
        case 'pull_request': {
            const url = typeof artefact.content.url === 'string' ? artefact.content.url : ''
            return `${prReference(url)} linked`
        }
        case 'implementation_decision': {
            const targets = (artefact.content as ImplementationDecisionContent).targets ?? []
            return targets.length === 1
                ? `${prReference(targets[0].pr_url)} assessed`
                : targets.length > 1
                  ? 'Open PRs assessed'
                  : 'Open PR assessed'
        }
        case 'implementation_replacement': {
            const targets = (artefact.content as ImplementationReplacementContent).decision?.targets ?? []
            return targets.length === 1
                ? `Replacing ${prReference(targets[0].pr_url)}`
                : targets.length > 1
                  ? `Replacing ${targets.length} PRs`
                  : 'PR replacement started'
        }
        case 'implementation_handover': {
            const content = artefact.content as ImplementationHandoverContent
            const replacements = content.replacement_pr_urls ?? []
            const results = Object.entries(content.results ?? {})
            if (
                content.status === 'completed' &&
                replacements.length === 1 &&
                results.length === 1 &&
                results[0][1] !== 'skipped'
            ) {
                const replacement = parsePrUrlParts(replacements[0])
                const previous = parsePrUrlParts(results[0][0])
                if (replacement && previous && replacement.repoSlug.toLowerCase() === previous.repoSlug.toLowerCase()) {
                    return `PR #${replacement.number} replaced #${previous.number}`
                }
            }
            return (
                {
                    processing: 'PR replacement in progress',
                    completed: 'PR replacement completed',
                    failed: 'PR replacement failed',
                    cancelled: 'PR replacement canceled',
                    needs_attention: 'PR replacement needs attention',
                }[content.status] ?? 'PR replacement update'
            )
        }
        default:
            return artefactTypeLabel(artefact.type)
    }
}
