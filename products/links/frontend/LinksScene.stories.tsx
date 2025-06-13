import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { LinkType } from '~/types'

const LINKS_RESULT: LinkType[] = [
    {
        id: '0187c22c-06d9-0000-34fe-daa2e2afb503',
        redirect_url: 'https://www.google.com',
        short_link_domain: 'phog.gg',
        short_code: 'google',
        description: 'Test link for Google',
        created_at: '2023-04-27T11:29:30.798968Z',
        updated_at: '2023-04-27T11:29:30.798968Z',
        created_by: {
            id: 123456,
            uuid: '0187c22c-06d9-0000-34fe-daa2e2afb504',
            distinct_id: '0187c22c-06d9-0000-34fe-daa2e2afb505',
            first_name: 'John',
            email: 'john@example.com',
        },
    },
    {
        id: '0187c22d-06d9-0000-34fe-daa2e2afb503',
        redirect_url: 'https://www.posthog.com',
        short_link_domain: 'phog.gg',
        short_code: 'posthog',
        description: 'Test link for PostHog',
        created_at: '2023-04-27T11:29:30.798968Z',
        updated_at: '2023-04-27T11:29:30.798968Z',
        created_by: {
            id: 123456,
            uuid: '0187c22c-06d9-0000-34fe-daa2e2afb504',
            distinct_id: '0187c22c-06d9-0000-34fe-daa2e2afb505',
            first_name: 'John',
            email: 'john@example.com',
        },
    },
    {
        id: '0187c22e-06d9-0000-34fe-daa2e2afb503',
        redirect_url: 'https://www.verylooooonglink.com?utm_source=test',
        short_link_domain: 'phog.gg',
        short_code: 'short',
        description: 'Test link for a very long link',
        created_at: '2023-04-27T11:29:30.798968Z',
        updated_at: '2023-04-27T11:29:30.798968Z',
        created_by: {
            id: 123456,
            uuid: '0187c22c-06d9-0000-34fe-daa2e2afb504',
            distinct_id: '0187c22c-06d9-0000-34fe-daa2e2afb505',
            first_name: 'John',
            email: 'john@example.com',
        },
    },
]

const meta: Meta = {
    title: 'Scenes-App/Links',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/links': {
                    count: 2,
                    results: LINKS_RESULT as any[],
                    next: null,
                    previous: null,
                },
                '/api/projects/:team_id/links/:linkId/': LINKS_RESULT[0],
            },
        }),
    ],
}
export default meta
export function LinksList(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.links())
    }, [])
    return <App />
}

export function NewLink(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.link('new'))
    }, [])
    return <App />
}

export function LinkDetails(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.link('0187c22c-06d9-0000-34fe-daa2e2afb503'))
    }, [])
    return <App />
}
