import { useQuery } from '@tanstack/react-query'

import { type RegionId, regionForHost } from '@/auth/regions'
import { useDataMode } from '@/demo/demoMode'

const STATUS_PAGE = 'https://www.posthogstatus.com'
const FIVE_MINUTES = 5 * 60_000

interface Component {
    group_name?: string
    name: string
}

interface StatusEvent {
    name: string
    affected_components: Component[]
}

interface Summary {
    ongoing_incidents: (StatusEvent & { id: string })[]
    in_progress_maintenances: StatusEvent[]
}

export interface PostHogStatus {
    pageUrl: string
    summary?: string
    aiIncident?: { title: string; url: string }
}

export function regionalStatus(summary: Summary, region: 'us' | 'eu'): PostHogStatus {
    const group = region === 'us' ? 'US Cloud' : 'EU Cloud'
    const inRegion = (component: Component): boolean =>
        component.group_name?.replace(/[^\p{L}\p{N}\s]/gu, '').trim() === group
    const relevant = (event: StatusEvent): boolean =>
        event.affected_components.length === 0 || event.affected_components.some(inRegion)
    const incident = summary.ongoing_incidents.find(relevant)
    const maintenance = summary.in_progress_maintenances.find(relevant)
    const ai = summary.ongoing_incidents.find((event) =>
        event.affected_components.some((component) => component.name === 'PostHog AI' && inRegion(component))
    )
    return {
        pageUrl: `${STATUS_PAGE}/${region}`,
        summary: incident?.name ?? maintenance?.name,
        aiIncident: ai && { title: ai.name, url: `${STATUS_PAGE}/incidents/${encodeURIComponent(ai.id)}` },
    }
}

export function usePostHogStatus(host: string | undefined): PostHogStatus {
    const mode = useDataMode()
    const region: RegionId = mode === 'live' && host ? regionForHost(host) : 'custom'
    const { data } = useQuery({
        queryKey: ['posthog-status', region],
        enabled: region !== 'custom',
        queryFn: async ({ signal }): Promise<PostHogStatus> => {
            if (region === 'custom') return { pageUrl: STATUS_PAGE }
            const response = await fetch(`${STATUS_PAGE}/api/v1/summary`, { signal, credentials: 'omit' })
            if (!response.ok) throw new Error(`Status page returned ${response.status}`)
            return regionalStatus(await response.json(), region)
        },
        staleTime: FIVE_MINUTES,
        refetchInterval: FIVE_MINUTES,
        refetchOnWindowFocus: true,
    })
    return data ?? { pageUrl: region === 'custom' ? STATUS_PAGE : `${STATUS_PAGE}/${region}` }
}
