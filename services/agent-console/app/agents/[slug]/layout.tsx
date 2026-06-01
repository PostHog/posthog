/**
 * `/agents/[slug]` route layout — owns the shared chrome (header,
 * banners, tab strip) and provides the fetched agent + revisions to
 * child segments via `AgentContext`. The layout stays mounted across
 * tab navigations, so children only re-render on segment changes and
 * the dock above stays alive through the whole flow.
 *
 * The layout is a client wrapper (we need browser navigation +
 * Context); the page-level RSC at `[slug]/page.tsx` is unchanged in
 * shape but its inner content moves into per-tab segments.
 */

'use client'

import { notFound } from 'next/navigation'
import { use } from 'react'

import { AgentProvider } from '@/components/agent-context'
import { AgentLayout } from '@/components/AgentLayout'
import { AgentDetailSkeleton } from '@/components/PageSkeletons'

export default function AgentSegmentLayout({
    children,
    params,
}: {
    children: React.ReactNode
    params: Promise<{ slug: string }>
}): React.ReactElement {
    // `use(params)` unwraps Next 15+'s async params in a client component.
    // The slug is stable for the lifetime of the segment; the layout
    // doesn't re-mount on intra-segment navigations.
    const { slug } = use(params)

    return (
        <AgentProvider
            slug={slug}
            fallback={<AgentDetailSkeleton />}
            notFoundFallback={<NotFoundTrigger />}
            errorFallback={(err) => (
                <div className="px-6 py-6 text-sm text-destructive-foreground">Failed to load: {err.message}</div>
            )}
        >
            <AgentLayout>{children}</AgentLayout>
        </AgentProvider>
    )
}

/**
 * `notFound()` must be called during render, not from an event handler
 * or effect — so the provider renders this component as its 404
 * fallback and `notFound()` fires synchronously during render.
 */
function NotFoundTrigger(): never {
    notFound()
}
