import { MarketingAnalyticsConversionAction } from '~/queries/schema/schema-general'

export interface ConversionActionAccount {
    campaignTable: string
    account: string
    actions: MarketingAnalyticsConversionAction[]
    /** No action of the account is selected, so recommendations count its primary actions. */
    countsPrimary: boolean
}

export function isPrimaryConversionAction(action: MarketingAnalyticsConversionAction): boolean {
    return action.primaryConversions > 0
}

export function conversionActionAccounts(
    options: MarketingAnalyticsConversionAction[],
    selection: string[]
): ConversionActionAccount[] {
    const accounts = new Map<string, ConversionActionAccount>()
    for (const option of options) {
        const account = accounts.get(option.campaignTable) ?? {
            campaignTable: option.campaignTable,
            account: option.account,
            actions: [],
            countsPrimary: true,
        }
        account.actions.push(option)
        accounts.set(option.campaignTable, account)
    }
    for (const account of accounts.values()) {
        // The backend also assigns a saved action to an account by its customer prefix, even without recent rows.
        const prefixes = new Set(account.actions.map((action) => customerPrefix(action.action)))
        account.countsPrimary = !selection.some(
            (action) =>
                account.actions.some((listed) => listed.action === action) || prefixes.has(customerPrefix(action))
        )
    }
    return [...accounts.values()]
}

function customerPrefix(action: string): string {
    return action.split('/conversionActions/')[0]
}

export function withConversionAction(selection: string[], action: string, checked: boolean): string[] {
    const rest = selection.filter((selected) => selected !== action)
    return checked ? [...rest, action] : rest
}

export function sameConversionActions(a: string[], b: string[]): boolean {
    const set = new Set(a)
    return set.size === new Set(b).size && b.every((action) => set.has(action))
}

export function conversionActionsLabel(saved: string[]): string {
    if (saved.length === 0) {
        return 'Primary conversion actions'
    }
    return saved.length === 1 ? '1 conversion action' : `${saved.length} conversion actions`
}
