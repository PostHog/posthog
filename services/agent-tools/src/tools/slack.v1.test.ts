import { makeCtx } from '../test-helpers'
import { slackPostMessageV1, slackUpdateMessageV1, slackReactV1 } from './slack.v1'

const originalFetch = global.fetch

describe('slack.* tools', () => {
    afterEach(() => {
        global.fetch = originalFetch
    })

    function mockFetch(body: Record<string, unknown>): void {
        global.fetch = jest.fn(async () => ({
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

    it('propagates slack api errors', async () => {
        global.fetch = jest.fn(async () => ({
            ok: true,
            status: 200,
            json: async () => ({ ok: false, error: 'channel_not_found' }),
        })) as unknown as typeof fetch
        await expect(
            slackPostMessageV1.run({ team_integration_id: 'slack:T01', channel: 'C99', text: 'hi' }, ctxWithSlack())
        ).rejects.toThrow(/channel_not_found/)
    })
})
