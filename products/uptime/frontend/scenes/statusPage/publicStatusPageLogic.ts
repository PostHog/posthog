import { afterMount, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { Incident, MonitorSummary } from '../uptimeSceneLogic'
import type { publicStatusPageLogicType } from './publicStatusPageLogicType'

export interface PublicStatusPage {
    title: string
    monitors: MonitorSummary[]
    published_at: string | null
    ongoing_incidents: Incident[]
    recent_incidents: Incident[]
}

export interface PublicStatusPageLogicProps {
    slug: string
}

export const publicStatusPageLogic = kea<publicStatusPageLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'statusPage', 'publicStatusPageLogic']),
    props({} as PublicStatusPageLogicProps),
    key((props) => props.slug),

    loaders(({ props }) => ({
        page: [
            null as PublicStatusPage | null,
            {
                loadPage: async () => {
                    return await api.get<PublicStatusPage>(`api/uptime/public_status_pages/${props.slug}/`)
                },
            },
        ],
    })),

    reducers({
        loadFailed: [
            false,
            {
                loadPageFailure: () => true,
                loadPageSuccess: () => false,
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadPage()
    }),
])
