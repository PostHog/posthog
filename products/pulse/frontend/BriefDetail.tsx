import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { BriefSectionApi, BriefSectionCitationApi } from './generated/api.schemas'
import { ProductBriefStatusEnumApi } from './generated/api.schemas'
import { pulseLogic } from './pulseLogic'

function assertNever(value: never): never {
    throw new Error(`Unhandled brief status: ${String(value)}`)
}

export function BriefDetail(): JSX.Element | null {
    const { briefDetail, briefDetailLoading, briefDetailLoadFailed, briefDetailSections, selectedBriefId } =
        useValues(pulseLogic)
    const { loadBriefDetail } = useActions(pulseLogic)

    if (briefDetailLoadFailed && selectedBriefId) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Retry', onClick: () => loadBriefDetail({ briefId: selectedBriefId }) }}
            >
                Couldn't load this brief. It may have been deleted, or the request failed.
            </LemonBanner>
        )
    }

    if (!briefDetail || briefDetail.id !== selectedBriefId) {
        return briefDetailLoading ? <Spinner /> : null
    }

    // Exhaustive over the status enum — a new backend status fails compilation at assertNever.
    switch (briefDetail.status) {
        case ProductBriefStatusEnumApi.Generating:
            return (
                <div className="flex items-center gap-2 border rounded p-8 justify-center">
                    <Spinner />
                    <span>Generating your brief…</span>
                </div>
            )
        case ProductBriefStatusEnumApi.Failed:
            return <LemonBanner type="error">{briefDetail.error || 'Brief generation failed.'}</LemonBanner>
        case ProductBriefStatusEnumApi.Quiet:
            return (
                <div className="border rounded p-8 text-center text-muted">
                    Quiet period — nothing confident to report
                </div>
            )
        case ProductBriefStatusEnumApi.Ready:
            return (
                <div className="flex flex-col gap-6">
                    {briefDetailSections.map((section, index) => (
                        <BriefSectionCard key={`${section.kind}-${index}`} section={section} />
                    ))}
                </div>
            )
        default:
            return assertNever(briefDetail.status)
    }
}

function BriefSectionCard({ section }: { section: BriefSectionApi }): JSX.Element {
    return (
        <div className="border rounded p-4 flex flex-col gap-2">
            <h3 className="mb-0">{section.title}</h3>
            {/* LLM-generated markdown must not auto-load arbitrary image URLs (tracking-pixel / IP-leak vector). */}
            <LemonMarkdown disableImages>{section.markdown}</LemonMarkdown>
            {section.citations.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {section.citations.map((citation) => (
                        <CitationTag key={`${citation.type}:${citation.ref}`} citation={citation} />
                    ))}
                </div>
            )}
        </div>
    )
}

function CitationTag({ citation }: { citation: BriefSectionCitationApi }): JSX.Element {
    // The backend resolves each ref to a display label and deep link, so we render those directly.
    const tag = <LemonTag>{citation.label}</LemonTag>
    return citation.url ? <Link to={citation.url}>{tag}</Link> : tag
}
