'use client'

import { notFound } from 'next/navigation'
import { use } from 'react'

import { useSessionTeamId } from '@/components/session-context'
import { listNativeTools, type NativeToolCatalogEntry } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

import { NativeToolDetail } from './native-tool-detail'

export default function NativeToolPage({ params }: { params: Promise<{ id: string }> }): React.ReactElement {
    const { id: rawId } = use(params)
    const id = decodeURIComponent(rawId)
    const teamId = useSessionTeamId()!
    const res = useResource(() => listNativeTools(teamId).catch(() => [] as NativeToolCatalogEntry[]), [teamId])

    if (res.loading && !res.data) {
        return <div className="mx-auto max-w-5xl px-6 py-6 text-sm text-muted-foreground">Loading…</div>
    }
    const tool = (res.data ?? []).find((t) => t.id === id)
    if (!tool) {
        notFound()
    }
    return <NativeToolDetail tool={tool} />
}
