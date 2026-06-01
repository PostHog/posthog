'use client'

import { notFound } from 'next/navigation'
import { use, useEffect, useState } from 'react'

import { useSessionTeamId } from '@/components/session-context'
import {
    getCustomToolTemplate,
    listCustomToolTemplateUsages,
    listCustomToolTemplateVersions,
} from '@/lib/registryClient'
import type { CustomToolTemplateDetail } from '@/lib/registryFixtures'

import { CustomToolDetail } from './custom-tool-detail'

export default function CustomToolPage({ params }: { params: Promise<{ name: string }> }): React.ReactElement {
    const { name: rawName } = use(params)
    const name = decodeURIComponent(rawName)
    const teamId = useSessionTeamId()
    const [tool, setTool] = useState<CustomToolTemplateDetail | null>(null)
    const [missing, setMissing] = useState(false)

    useEffect(() => {
        if (teamId == null) {
            return
        }
        let cancelled = false
        ;(async () => {
            try {
                const [detail, versions, usages] = await Promise.all([
                    getCustomToolTemplate(teamId, name),
                    listCustomToolTemplateVersions(teamId, name),
                    listCustomToolTemplateUsages(teamId, name),
                ])
                if (cancelled) {
                    return
                }
                const history = versions
                    .filter((v) => v.version !== detail.version)
                    .map((v) => ({
                        version: v.version,
                        updated_at: v.updated_at,
                        created_by: v.created_by?.first_name ?? null,
                    }))
                setTool({
                    ...detail,
                    description: detail.description ?? '',
                    created_by: detail.created_by?.first_name ?? null,
                    requires_secrets: [...(detail.requires_secrets ?? [])],
                    args_schema: (detail.args_schema as Record<string, unknown>) ?? {},
                    returns_schema: detail.returns_schema as Record<string, unknown> | undefined,
                    history,
                    usages: usages.map((u) => ({
                        agent_slug: u.agent_slug,
                        agent_name: u.agent_name,
                        revision_short_id: u.revision_short_id,
                        pinned_version: u.pinned_version,
                    })),
                })
            } catch (e) {
                if (!cancelled && (e as { status?: number }).status === 404) {
                    setMissing(true)
                }
            }
        })()
        return () => {
            cancelled = true
        }
    }, [teamId, name])

    if (missing) {
        notFound()
    }
    if (!tool) {
        return <div className="px-6 py-6 text-sm text-muted-foreground">Loading custom tool template…</div>
    }
    return <CustomToolDetail tool={tool} />
}
