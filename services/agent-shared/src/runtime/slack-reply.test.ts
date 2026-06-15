import { describe, expect, it, vi } from 'vitest'

import { HttpFetcher } from './http-client'
import { isSlackTriggerMetadata, postSlackReply, slackTextFromContent } from './slack-reply'

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

function httpReturning(res: Response | Error): { http: HttpFetcher; fetch: ReturnType<typeof vi.fn> } {
    const fetch = vi.fn(async () => {
        if (res instanceof Error) {
            throw res
        }
        return res
    })
    return { http: { fetch } as unknown as HttpFetcher, fetch }
}

describe('postSlackReply', () => {
    it('posts to chat.postMessage on the thread and returns true', async () => {
        const { http, fetch } = httpReturning(jsonResponse({ ok: true }))
        const ok = await postSlackReply(http, {
            token: 'xoxb-123',
            channel: 'C1',
            thread_ts: '111.222',
            text: 'here is your answer',
        })
        expect(ok).toBe(true)
        const [url, init] = fetch.mock.calls[0]
        expect(url).toBe('https://slack.com/api/chat.postMessage')
        expect((init as RequestInit).headers).toMatchObject({ Authorization: 'Bearer xoxb-123' })
        const body = JSON.parse((init as RequestInit).body as string)
        expect(body).toEqual({ channel: 'C1', thread_ts: '111.222', text: 'here is your answer' })
    })

    it('skips empty text without calling slack', async () => {
        const { http, fetch } = httpReturning(jsonResponse({ ok: true }))
        const ok = await postSlackReply(http, { token: 'xoxb', channel: 'C1', thread_ts: 't', text: '   ' })
        expect(ok).toBe(false)
        expect(fetch).not.toHaveBeenCalled()
    })

    it('warns and skips when the bot token is missing', async () => {
        const { http, fetch } = httpReturning(jsonResponse({ ok: true }))
        const warn = vi.fn()
        const ok = await postSlackReply(http, {
            token: undefined,
            channel: 'C1',
            thread_ts: 't',
            text: 'hi',
            logger: { warn },
        })
        expect(ok).toBe(false)
        expect(fetch).not.toHaveBeenCalled()
        expect(warn).toHaveBeenCalledWith(expect.objectContaining({ channel: 'C1' }), 'slack_reply_no_bot_token')
    })

    it('returns false and warns on a slack error body', async () => {
        const { http } = httpReturning(jsonResponse({ ok: false, error: 'channel_not_found' }))
        const warn = vi.fn()
        const ok = await postSlackReply(http, {
            token: 'xoxb',
            channel: 'C1',
            thread_ts: 't',
            text: 'hi',
            logger: { warn },
        })
        expect(ok).toBe(false)
        expect(warn).toHaveBeenCalledWith(
            expect.objectContaining({ slack_error: 'channel_not_found' }),
            'slack_reply_post_failed'
        )
    })

    it('swallows a thrown fetch and returns false', async () => {
        const { http } = httpReturning(new Error('network down'))
        const warn = vi.fn()
        const ok = await postSlackReply(http, {
            token: 'xoxb',
            channel: 'C1',
            thread_ts: 't',
            text: 'hi',
            logger: { warn },
        })
        expect(ok).toBe(false)
        expect(warn).toHaveBeenCalledWith(expect.objectContaining({ err: 'network down' }), 'slack_reply_post_threw')
    })
})

describe('slackTextFromContent', () => {
    it('joins text blocks and ignores non-text / empty blocks', () => {
        const text = slackTextFromContent([
            { type: 'text', text: 'first' },
            { type: 'toolCall' },
            { type: 'text', text: 'second' },
            { type: 'text', text: '   ' },
        ])
        expect(text).toBe('first\n\nsecond')
    })

    it('returns empty string for a pure tool-call turn', () => {
        expect(slackTextFromContent([{ type: 'toolCall' }])).toBe('')
    })
})

describe('isSlackTriggerMetadata', () => {
    it('accepts a well-formed slack metadata object', () => {
        expect(
            isSlackTriggerMetadata({ type: 'slack', workspace_id: 'W', channel: 'C1', ts: 't', thread_ts: 't' })
        ).toBe(true)
    })

    it.each([null, undefined, {}, { type: 'chat' }, { type: 'slack', channel: 'C1' }])(
        'rejects non-slack / incomplete metadata: %j',
        (meta) => {
            expect(isSlackTriggerMetadata(meta)).toBe(false)
        }
    )
})
