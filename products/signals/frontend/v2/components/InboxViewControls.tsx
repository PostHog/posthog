import { useActions, useValues } from 'kea'

import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { urls } from 'scenes/urls'

import { InboxDemoScope } from '../types'
import { v2InboxLogic } from '../v2InboxLogic'

const SCOPE_OPTIONS: { value: InboxDemoScope; label: string }[] = [
    { value: 'for-you', label: 'For you' },
    { value: 'project', label: 'Entire project' },
]

/** Focus mode entry point and the For you / Entire project switch, shared by both reports layouts. */
export function InboxViewControls(): JSX.Element {
    const { scope } = useValues(v2InboxLogic)
    const { setScope } = useActions(v2InboxLogic)

    return (
        <>
            <LemonButton
                type="primary"
                size="small"
                to={urls.v2Focus()}
                sideIcon={<KeyboardShortcut f />}
                data-attr="v2-focus-mode"
            >
                Focus mode
            </LemonButton>
            <LemonSegmentedButton
                size="small"
                value={scope}
                onChange={setScope}
                options={SCOPE_OPTIONS.map((option) => ({
                    ...option,
                    'data-attr': `v2-scope-${option.value}`,
                }))}
            />
        </>
    )
}
