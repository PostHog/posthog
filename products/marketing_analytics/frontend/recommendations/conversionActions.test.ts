import { MarketingAnalyticsConversionAction } from '~/queries/schema/schema-general'

import { conversionActionAccounts, sameConversionActions, withConversionAction } from './conversionActions'

const action = (id: string, campaignTable: string, primaryConversions = 0): MarketingAnalyticsConversionAction => ({
    action: id,
    name: id,
    account: campaignTable,
    campaignTable,
    primaryConversions,
    allConversions: 1,
    recent: true,
})

const A_PURCHASE = 'customers/1/conversionActions/10'
const A_SIGNUP = 'customers/1/conversionActions/20'
const B_LEAD = 'customers/2/conversionActions/30'
const OPTIONS = [action(A_PURCHASE, 'a', 3), action(A_SIGNUP, 'a'), action(B_LEAD, 'b', 2)]

describe('conversion actions', () => {
    it.each([
        { selection: [], countsPrimary: { a: true, b: true } },
        { selection: [A_SIGNUP], countsPrimary: { a: false, b: true } },
        { selection: [A_SIGNUP, B_LEAD], countsPrimary: { a: false, b: false } },
        { selection: ['customers/2/conversionActions/99'], countsPrimary: { a: true, b: false } },
    ])(
        'an account counts its primary actions until one of its actions is selected: $selection',
        ({ selection, countsPrimary }) => {
            const accounts = conversionActionAccounts(OPTIONS, selection)
            expect(
                Object.fromEntries(accounts.map((account) => [account.campaignTable, account.countsPrimary]))
            ).toEqual(countsPrimary)
            expect(accounts.map((account) => account.actions.length)).toEqual([2, 1])
        }
    )

    it.each([
        { selection: ['x'], checked: true, expected: ['x', 'y'] },
        { selection: ['x', 'y'], checked: true, expected: ['x', 'y'] },
        { selection: ['x', 'y'], checked: false, expected: ['x'] },
    ])('toggles y without duplicating it: $selection, $checked', ({ selection, checked, expected }) => {
        expect(withConversionAction(selection, 'y', checked)).toEqual(expected)
    })

    it.each([
        { a: ['x', 'y'], b: ['y', 'x'], same: true },
        { a: ['x'], b: ['x', 'y'], same: false },
        { a: [], b: [], same: true },
    ])('compares selections ignoring order: $a vs $b', ({ a, b, same }) => {
        expect(sameConversionActions(a, b)).toBe(same)
    })
})
