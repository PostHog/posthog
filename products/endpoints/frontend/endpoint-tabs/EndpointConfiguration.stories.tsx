import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { getAppContext } from 'lib/utils/getAppContext'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, type EndpointVersionType } from '~/types'

import { endpointLogic } from '../endpointLogic'
import { endpointSceneLogic } from '../endpointSceneLogic'
import { EndpointConfiguration } from './EndpointConfiguration'

const endpoint: EndpointVersionType = {
    id: '01900000-0000-7000-8000-000000000001',
    name: 'daily_totals',
    description: '',
    query: { kind: NodeKind.HogQLQuery, query: 'SELECT 1 AS total' },
    is_active: true,
    user_access_level: AccessControlLevel.Editor,
    endpoint_path: '/api/projects/1/endpoints/daily_totals/run/',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
    created_by: null,
    data_freshness_seconds: 86400,
    is_materialized: false,
    current_version: 1,
    current_version_id: '01900000-0000-7000-8000-000000000002',
    versions_count: 1,
    version: 1,
    version_id: '01900000-0000-7000-8000-000000000002',
    endpoint_is_active: true,
    version_created_at: '2026-01-01T00:00:00Z',
    version_created_by: null,
    materialization: { can_materialize: true, enabled: false, ready: false },
}

function getEndpoint(hibernated: boolean): EndpointVersionType {
    return {
        ...endpoint,
        materialization: {
            ...endpoint.materialization!,
            hibernated,
            hibernated_at: hibernated ? '2026-03-01T00:00:00Z' : null,
        },
    }
}

function ConfigurationStory({ hibernated }: { hibernated: boolean }): JSX.Element {
    const { loadEndpointSuccess } = useActions(endpointLogic)
    useValues(endpointSceneLogic)
    useEffect(() => {
        const appContext = getAppContext()
        if (!appContext) {
            return
        }
        const originalAccess = appContext.resource_access_control
        appContext.resource_access_control = { ...originalAccess, endpoint: AccessControlLevel.Editor }
        loadEndpointSuccess(getEndpoint(hibernated))
        return () => {
            appContext.resource_access_control = originalAccess
        }
    }, [hibernated, loadEndpointSuccess])
    return <EndpointConfiguration />
}

const meta: Meta<typeof ConfigurationStory> = {
    title: 'Endpoints/Configuration',
    component: ConfigurationStory,
    parameters: {
        layout: 'padded',
        featureFlags: [],
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    decorators: [
        (Story, context) =>
            mswDecorator({
                get: {
                    '/api/environments/:team_id/endpoints/daily_totals/': getEndpoint(context.args.hibernated),
                    '/api/environments/:team_id/endpoints/daily_totals/versions/': { results: [endpoint] },
                },
            })(Story, context),
    ],
}
export default meta

type Story = StoryObj<typeof ConfigurationStory>

export const Disabled: Story = { args: { hibernated: false } }
export const Hibernated: Story = { args: { hibernated: true } }
export const HibernatedNarrow: Story = {
    ...Hibernated,
    decorators: [
        (Story) => (
            <div className="w-130">
                <Story />
            </div>
        ),
    ],
}
