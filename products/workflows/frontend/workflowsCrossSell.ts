import type { MouseEvent } from 'react'

import { addProductIntentForCrossSell } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

const MIDDLE_BUTTON = 1

interface CrossSellLinkProps {
    onClickCapture: () => void
    onAuxClick: (event: MouseEvent<HTMLElement>) => void
}

function recordCrossSell(to: ProductKey, intentContext: ProductIntentContext): void {
    void addProductIntentForCrossSell({ from: ProductKey.WORKFLOWS, to, intent_context: intentContext }).catch(
        () => null
    )
}

// Spread onto a `Link` or a `LemonButton` with `to`. Its `onClick` skips Cmd/Ctrl-clicks and never sees a middle click.
export function crossSellLinkProps(to: ProductKey, intentContext: ProductIntentContext): CrossSellLinkProps {
    return {
        onClickCapture: () => recordCrossSell(to, intentContext),
        onAuxClick: (event) => {
            if (event.button === MIDDLE_BUTTON) {
                recordCrossSell(to, intentContext)
            }
        },
    }
}
