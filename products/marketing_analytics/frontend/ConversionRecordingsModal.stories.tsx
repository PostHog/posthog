import { Meta, StoryObj } from '@storybook/react'

import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { recordings } from 'scenes/session-recordings/__mocks__/recordings'

import { useStorybookMocks } from '~/mocks/browser'

import { ConversionRecordingsModal } from './ConversionRecordingsModal'
import { ConversionRecordingsRequestApi, ConversionRecordingsResponseApi } from './generated/api.schemas'

const meta: Meta<typeof ConversionRecordingsModal> = {
    title: 'Marketing Analytics/Conversion recordings',
    component: ConversionRecordingsModal,
    args: {
        goalName: 'Purchases',
        request: {
            source: { kind: 'MarketingAnalyticsTableQuery', properties: [], dateRange: { date_from: '-7d' } },
            goal_id: 'purchase',
            group: 'winter-sale',
            source_name: 'google',
        },
        onClose: () => {},
    },
    parameters: {
        mockDate: '2023-08-11T12:05:00Z',
        testOptions: { waitForSelector: '.LemonModal', snapshotTargetSelector: '.LemonModal' },
    },
}
export default meta
type Story = StoryObj<typeof meta>

const sessions: ConversionRecordingsResponseApi = {
    session_ids: recordings.map(({ id }) => id),
    has_more: false,
    preparing: false,
}

export const WithRecordings: Story = {
    render: (args) => {
        useStorybookMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_recordings/': async ({ request }) => {
                    const { after } = (await request.json()) as ConversionRecordingsRequestApi
                    return {
                        ...sessions,
                        session_ids: after ? sessions.session_ids.slice(1) : sessions.session_ids.slice(0, 1),
                        has_more: !after,
                    }
                },
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as { query: { kind: string } }
                    return body.query.kind === 'EventsQuery'
                        ? recordingEventsJson
                        : {
                              columns: ['session_id', '$geoip_country_code', '$browser', '$device_type', '$os'],
                              results: recordings.map(({ id }) => [id, 'GB', 'Chrome', 'Desktop', 'Mac OS X']),
                          }
                },
            },
            get: {
                '/api/environments/:team_id/session_recordings': ({ request }) => {
                    const ids = JSON.parse(new URL(request.url).searchParams.get('session_ids') || '[]') as string[]
                    return { has_next: false, results: recordings.filter(({ id }) => ids.includes(id)), version: 1 }
                },
                '/api/environments/:team_id/session_recordings/:id': ({ params }) => ({
                    ...recordingMetaJson,
                    id: params.id,
                }),
                '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) =>
                    new URL(request.url).searchParams.get('source') === 'blob_v2'
                        ? new Response(snapshotsAsJSONLines())
                        : {
                              sources: [
                                  {
                                      source: 'blob_v2',
                                      start_timestamp: '2023-08-11T12:03:36.097000Z',
                                      end_timestamp: '2023-08-11T12:04:52.268000Z',
                                      blob_key: '0',
                                  },
                              ],
                          },
            },
        })
        return <ConversionRecordingsModal {...args} />
    },
    play: async ({ canvasElement }) => {
        let recording: HTMLElement | null = null
        for (let frame = 0; frame < 120 && !recording; frame++) {
            recording = canvasElement.ownerDocument.querySelector('.Playlist__list .ph-no-capture span.truncate')
            if (!recording) {
                await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
            }
        }
        if (!recording) {
            throw new Error('The conversion recording list did not load')
        }
        recording.click()
    },
    parameters: {
        testOptions: {
            waitForSelector: 'iframe.PlayerFrame__document >>> .PlayerFrame__content .replayer-wrapper iframe',
        },
    },
}

export const NoRecordings: Story = {
    render: (args) => {
        useStorybookMocks({
            post: { '/api/projects/:team_id/marketing_analytics/conversion_recordings/': sessions },
            get: { '/api/environments/:team_id/session_recordings': { has_next: false, results: [], version: 1 } },
        })
        return <ConversionRecordingsModal {...args} />
    },
}

export const Preparing: Story = {
    render: (args) => {
        useStorybookMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_recordings/': {
                    ...sessions,
                    session_ids: [],
                    preparing: true,
                },
            },
        })
        return <ConversionRecordingsModal {...args} />
    },
}

export const Empty: Story = {
    render: (args) => {
        useStorybookMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_recordings/': { ...sessions, session_ids: [] },
            },
        })
        return <ConversionRecordingsModal {...args} />
    },
}

export const QueryError: Story = {
    render: (args) => {
        useStorybookMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_recordings/': [
                    500,
                    { detail: 'Could not load conversion recordings.' },
                ],
            },
        })
        return <ConversionRecordingsModal {...args} />
    },
}
