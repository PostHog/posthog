'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useMemo } from 'react'

import { useAgent, useAgentReload, useRevisions } from '@/components/agent-context'
import { useDockStore } from '@/components/dock-context'
import { RevisionsBrowser } from '@/components/RevisionsBrowser'

type SpecSection = 'triggers' | 'tools' | 'skills' | 'secrets' | 'limits' | null

export function ConfigurationSegment(): React.ReactElement {
    const agent = useAgent()
    const revisions = useRevisions()
    const reload = useAgentReload()
    const router = useRouter()
    const searchParams = useSearchParams()
    const { enterPlayground } = useDockStore()

    const sortedRevisions = useMemo(
        () => [...revisions].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()),
        [revisions]
    )
    const defaultRevisionId = agent.live_revision ?? sortedRevisions[0]?.id ?? null

    const explicitRevisionId = searchParams?.get('revision') ?? null
    const selectedRevisionId = explicitRevisionId ?? defaultRevisionId
    const filePath = searchParams?.get('file') ?? null
    const section = parseSection(searchParams?.get('section'))

    // Single writer with a "what's changing" partial. Merges into the
    // current query string so each setter only owns its key, not the
    // others. `revision` collapses to the URL default to keep the
    // canonical link short.
    const pushParams = useCallback(
        (next: { revisionId?: string | null; section?: SpecSection; filePath?: string | null }) => {
            const params = new URLSearchParams(searchParams?.toString() ?? '')
            if (next.revisionId !== undefined) {
                if (next.revisionId && next.revisionId !== agent.live_revision) {
                    params.set('revision', next.revisionId)
                } else {
                    params.delete('revision')
                }
            }
            if (next.section !== undefined) {
                if (next.section) {
                    params.set('section', next.section)
                } else {
                    params.delete('section')
                }
            }
            if (next.filePath !== undefined) {
                if (next.filePath) {
                    params.set('file', next.filePath)
                } else {
                    params.delete('file')
                }
            }
            const qs = params.toString()
            router.push(`/agents/${agent.slug}/configuration${qs ? `?${qs}` : ''}`, { scroll: false })
        },
        [agent.live_revision, agent.slug, router, searchParams]
    )

    const onTryDraft = useCallback(
        (revisionId: string) => {
            enterPlayground({ id: agent.id, slug: agent.slug, name: agent.name }, { previewRevisionId: revisionId })
        },
        [agent.id, agent.name, agent.slug, enterPlayground]
    )

    return (
        <div className="mx-auto h-full max-w-5xl space-y-4 overflow-y-auto px-6 pb-6 pt-4">
            <RevisionsBrowser
                agent={agent}
                revisions={revisions}
                selectedRevisionId={selectedRevisionId}
                onSelectRevision={(id) => pushParams({ revisionId: id })}
                highlightedSection={section}
                focusedBundlePath={filePath}
                onSelectBundleFile={(path) => pushParams({ filePath: path })}
                onMutated={reload}
                onTryDraft={onTryDraft}
            />
        </div>
    )
}

function parseSection(raw: string | null | undefined): SpecSection {
    if (raw === 'triggers' || raw === 'tools' || raw === 'skills' || raw === 'secrets' || raw === 'limits') {
        return raw
    }
    return null
}
