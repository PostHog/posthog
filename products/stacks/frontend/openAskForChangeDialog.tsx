import posthog from 'posthog-js'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { retryImport } from 'lib/utils/retryImport'

import type { AskForChangeLogicProps } from './askForChangeLogic'

/** Opens "Ask for a change" over whatever scene is showing, from the banner or from a refused write. */
export function openAskForChangeDialog(props: AskForChangeLogicProps): void {
    // pinned: analytics event name and properties, renaming breaks dashboards
    posthog.capture('managed in code change form opened', {
        kind: props.binding.kind,
        entry_point: props.entryPoint,
    })
    // Loaded on open, so the form stays out of the bundle of every scene that shows the banner.
    void retryImport(() => import('./AskForChange')).then(({ AskForChange }) =>
        LemonDialog.open({
            title: 'Ask for a change',
            maxWidth: '36rem',
            primaryButton: null,
            secondaryButton: null,
            content: (closeDialog) => <AskForChange {...props} onClose={closeDialog} />,
        })
    )
}
