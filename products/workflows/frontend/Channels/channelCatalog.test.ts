import { ChannelStatus, summarizeChannel } from './channelCatalog'
import type { ChannelType } from './MessageChannels'

const email = (verified: boolean): any => ({ kind: 'email', config: { verified } })
const slack = (errors?: string): any => ({ kind: 'slack', config: {}, errors })
const github: any = { kind: 'github', config: {} }

describe('summarizeChannel', () => {
    test.each<[string, ChannelType, any[], ChannelStatus, number]>([
        ['nothing connected', 'email', [], 'not-set-up', 0],
        ['other kinds do not count', 'slack', [github, email(true)], 'not-set-up', 0],
        ['an unverified email address needs verification', 'email', [email(false)], 'needs-verification', 1],
        ['one verified address makes email active', 'email', [email(false), email(true)], 'active', 2],
        ['a connected slack workspace is active', 'slack', [slack()], 'active', 1],
        [
            'a connection with an error needs attention',
            'slack',
            [slack(), slack('TOKEN_REFRESH_FAILED')],
            'needs-attention',
            2,
        ],
    ])('%s', (_, kind, integrations, status, count) => {
        expect(summarizeChannel(kind, integrations)).toEqual({ kind, status, count })
    })
})
