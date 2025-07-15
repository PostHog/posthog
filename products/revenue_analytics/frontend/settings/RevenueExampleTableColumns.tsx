import { humanFriendlyNumber } from 'lib/utils'
import { CURRENCY_SYMBOL_TO_EMOJI_MAP } from 'lib/utils/geography/currency'
import { getCurrencySymbol } from 'lib/utils/geography/currency'

import { CurrencyCode } from '~/queries/schema/schema-general'

export const Revenue = ({ value, currency }: { value: number; currency: string }): JSX.Element => {
    const { symbol, isPrefix } = getCurrencySymbol(currency ?? CurrencyCode.USD)
    return <div>{`${isPrefix ? symbol : ''}${humanFriendlyNumber(value, 10, 2)}${isPrefix ? '' : ' ' + symbol}`}</div>
}

export const Currency = ({ currency }: { currency: string }): JSX.Element => {
    return (
        <div>
            {CURRENCY_SYMBOL_TO_EMOJI_MAP[currency as CurrencyCode]} {currency}
        </div>
    )
}
