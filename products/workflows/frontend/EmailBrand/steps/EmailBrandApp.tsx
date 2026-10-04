import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { emailBrandFlowLogic } from '../emailBrandFlowLogic'
import type { EmailBrandFlowProps } from '../emailBrandFlowLogic'

export function EmailBrandApp(props: EmailBrandFlowProps): JSX.Element {
    const logic = emailBrandFlowLogic(props)
    const { detection, busy, appRoot } = useValues(logic)
    const { chooseApp, setAppRoot } = useActions(logic)
    const roots = Array.from(new Set([detection?.app_root ?? '', ...(detection?.app_root_alternatives ?? [])]))
    return (
        <div className="max-w-lg mx-auto py-8 space-y-4">
            <div className="text-center">
                <h2>Which app should the email look like?</h2>
                <p>This repository has more than one app. Choose the app whose theme and logo you want to use.</p>
            </div>
            <LemonSelect
                value={appRoot}
                onChange={setAppRoot}
                options={roots.map((root) => ({ value: root, label: root || 'Repository root' }))}
                fullWidth
                data-attr="email-brand-app-root"
            />
            <LemonButton
                type="primary"
                onClick={() => chooseApp(appRoot)}
                loading={busy}
                center
                fullWidth
                data-attr="email-brand-choose-app"
            >
                Use this app
            </LemonButton>
        </div>
    )
}
