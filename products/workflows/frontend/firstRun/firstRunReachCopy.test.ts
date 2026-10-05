import { firstRunReachCopy } from './firstRunReachCopy'
import type { FirstRunReach } from './firstRunReachLogic'

describe('firstRunReachCopy', () => {
    it.each<[string, Omit<FirstRunReach, 'senderAddress'>, string]>([
        [
            'no own domain',
            { counts: { reached: 3, notReachedYet: 1240 }, ownDomain: 'none' },
            "only to your organization's 3\u00a0verified members. The 1,240\u00a0people in this project with an email address can get these emails once you send from your own domain.",
        ],
        [
            'a domain not verified yet',
            { counts: { reached: 1, notReachedYet: 1 }, ownDomain: 'verifying' },
            "only to your organization's 1\u00a0verified member. Your domain is not verified yet. Once it is, the 1\u00a0person in this project with an email address can get these emails too.",
        ],
        [
            'zero counts',
            { counts: { reached: 0, notReachedYet: 0 }, ownDomain: 'none' },
            "only to your organization's 0\u00a0verified members. No one in this project has an email address yet.",
        ],
        [
            'no counts',
            { counts: null, ownDomain: 'none' },
            'only to verified members of your organization. The people in this project can get these emails once you send from your own domain.',
        ],
    ])('says who it reaches with %s', (_, reach, expected) => {
        expect(firstRunReachCopy({ senderAddress: 'sandbox@example.com', ...reach })).toBe(expected)
    })
})
