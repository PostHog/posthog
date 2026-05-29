import { makeCtx } from '../test-helpers'
import {
    slackPostMessageV1,
    slackReactV1,
    slackReadChannelV1,
    slackReadThreadV1,
    slackUpdateMessageV1,
} from './slack.v1'

const originalFetch = global.fetch

describe('slack.* tools', () => {
    afterEach(() => {
        global.fetch = originalFetch
    })

    function mockFetch(body: Record<string, unknown>): void {
        global.fetch = vi.fn(async () => ({
            ok: true,
            status: 200,
            json: async () => ({ ok: true, ...body }),
        })) as unknown as typeof fetch
    }

    function ctxWithSlack(): ReturnType<typeof makeCtx> {
        return makeCtx({
            integrations: {
                'slack:T01': { kind: 'slack', access_token: 'xoxb-test' },
            },
        })
    }

    it('post_message returns ts + channel', async () => {
        mockFetch({ ts: '123.456', channel: 'C01' })
        const out = await slackPostMessageV1.run(
            { team_integration_id: 'slack:T01', channel: 'C01', text: 'hi' },
            ctxWithSlack()
        )
        expect(out).toEqual({ ts: '123.456', channel: 'C01' })
    })

    it('rejects missing integration', async () => {
        await expect(
            slackPostMessageV1.run({ team_integration_id: 'slack:T01', channel: 'C01', text: 'hi' }, makeCtx())
        ).rejects.toThrow(/slack integration/)
    })

    it('update_message returns ok', async () => {
        mockFetch({})
        const out = await slackUpdateMessageV1.run(
            { team_integration_id: 'slack:T01', channel: 'C01', ts: '123.456', text: 'edit' },
            ctxWithSlack()
        )
        expect(out).toEqual({ ok: true })
    })

    it('react returns ok', async () => {
        mockFetch({})
        const out = await slackReactV1.run(
            { team_integration_id: 'slack:T01', channel: 'C01', ts: '123.456', name: 'fire' },
            ctxWithSlack()
        )
        expect(out).toEqual({ ok: true })
    })

    it('read_channel returns projected messages + pagination', async () => {
        const fetchSpy = vi.fn(async () => ({
            ok: true,
            status: 200,
            json: async () => ({
                ok: true,
                messages: [
                    {
                        ts: '111.222',
                        user: 'U01',
                        text: 'hello',
                        thread_ts: '111.222',
                        reply_count: 3,
                        extra_field_we_drop: true,
                    },
                    { ts: '111.221', bot_id: 'B01', username: 'alertbot', text: 'PAGE', subtype: 'bot_message' },
                ],
                has_more: true,
                response_metadata: { next_cursor: 'cur-abc' },
            }),
        }))
        global.fetch = fetchSpy as never as typeof fetch
        const out = await slackReadChannelV1.run(
            { team_integration_id: 'slack:T01', channel: 'C01', limit: 50, oldest: '100.0' },
            ctxWithSlack()
        )
        expect(out.messages).toEqual([
            {
                ts: '111.222',
                user: 'U01',
                bot_id: undefined,
                username: undefined,
                text: 'hello',
                subtype: undefined,
                thread_ts: '111.222',
                reply_count: 3,
            },
            {
                ts: '111.221',
                user: undefined,
                bot_id: 'B01',
                username: 'alertbot',
                text: 'PAGE',
                subtype: 'bot_message',
                thread_ts: undefined,
                reply_count: undefined,
            },
        ])
        expect(out.has_more).toBe(true)
        expect(out.next_cursor).toBe('cur-abc')
        const calls = fetchSpy.mock.calls as unknown as Array<[string, RequestInit]>
        const body = JSON.parse(calls[0][1].body as string)
        expect(body).toMatchObject({ channel: 'C01', limit: 50, oldest: '100.0' })
        expect(body).not.toHaveProperty('latest')
        expect(body).not.toHaveProperty('cursor')
    })

    it('read_channel clamps limit to [1, 200]', async () => {
        const fetchSpy = vi.fn(async () => ({
            ok: true,
            status: 200,
            json: async () => ({ ok: true, messages: [], has_more: false }),
        }))
        global.fetch = fetchSpy as never as typeof fetch
        await slackReadChannelV1.run({ team_integration_id: 'slack:T01', channel: 'C01', limit: 9999 }, ctxWithSlack())
        const calls = fetchSpy.mock.calls as unknown as Array<[string, RequestInit]>
        const bodyHigh = JSON.parse(calls[0][1].body as string)
        expect(bodyHigh.limit).toBe(200)

        await slackReadChannelV1.run({ team_integration_id: 'slack:T01', channel: 'C01', limit: 0 }, ctxWithSlack())
        const bodyLow = JSON.parse(calls[1][1].body as string)
        expect(bodyLow.limit).toBe(1)
    })

    it('read_channel omits next_cursor when slack returns empty string', async () => {
        mockFetch({ messages: [], has_more: false, response_metadata: { next_cursor: '' } })
        const out = await slackReadChannelV1.run({ team_integration_id: 'slack:T01', channel: 'C01' }, ctxWithSlack())
        expect(out.next_cursor).toBeUndefined()
        expect(out.has_more).toBe(false)
    })

    it('read_thread passes ts as the parent and projects messages', async () => {
        const fetchSpy = vi.fn(async () => ({
            ok: true,
            status: 200,
            json: async () => ({
                ok: true,
                messages: [
                    { ts: '111.222', user: 'U01', text: 'parent', thread_ts: '111.222', reply_count: 1 },
                    { ts: '111.333', user: 'U02', text: 'reply', thread_ts: '111.222' },
                ],
                has_more: false,
            }),
        }))
        global.fetch = fetchSpy as never as typeof fetch
        const out = await slackReadThreadV1.run(
            { team_integration_id: 'slack:T01', channel: 'C01', thread_ts: '111.222' },
            ctxWithSlack()
        )
        expect(out.messages.map((m) => m.text)).toEqual(['parent', 'reply'])
        expect(out.has_more).toBe(false)
        const calls = fetchSpy.mock.calls as unknown as Array<[string, RequestInit]>
        const body = JSON.parse(calls[0][1].body as string)
        expect(body).toMatchObject({ channel: 'C01', ts: '111.222', limit: 50 })
    })

    it('propagates slack api errors', async () => {
        global.fetch = vi.fn(async () => ({
            ok: true,
            status: 200,
            json: async () => ({ ok: false, error: 'channel_not_found' }),
        })) as unknown as typeof fetch
        await expect(
            slackPostMessageV1.run({ team_integration_id: 'slack:T01', channel: 'C99', text: 'hi' }, ctxWithSlack())
        ).rejects.toThrow(/channel_not_found/)
    })
})
