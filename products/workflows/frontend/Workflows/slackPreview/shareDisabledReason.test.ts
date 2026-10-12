import { ShareFormState, getShareDisabledReason } from './shareDisabledReason'

const READY: ShareFormState = {
    integrationId: 1,
    channel: 'C0PREVIEW|#workflow-previews',
    threadLink: '',
    selectedEmailCount: 2,
    canUploadImages: true,
}

describe('getShareDisabledReason', () => {
    it.each<[string, Partial<ShareFormState>, string | undefined]>([
        ['ready to share to a channel', {}, undefined],
        [
            'ready to share into a thread',
            { channel: null, threadLink: 'https://acme.slack.com/archives/C0X/p1760000000123456' },
            undefined,
        ],
        ['no workspace', { integrationId: null }, 'Select a Slack workspace'],
        ['no destination', { channel: null }, 'Select a channel or paste a thread link'],
        [
            'a link that is not a Slack message',
            { threadLink: 'https://example.com/archives/C0X/p1760000000123456' },
            'Paste a link to a Slack message, copied with Copy link',
        ],
        ['more emails than Slack accepts', { selectedEmailCount: 11 }, 'Select at most 10 emails'],
        [
            'emails without the Slack file upload permission',
            { canUploadImages: false },
            'Reconnect Slack to share the emails, or deselect them',
        ],
        [
            'no emails without the Slack file upload permission',
            { canUploadImages: false, selectedEmailCount: 0 },
            undefined,
        ],
    ])('%s', (_name, overrides, expected) => {
        expect(getShareDisabledReason({ ...READY, ...overrides })).toBe(expected)
    })
})
