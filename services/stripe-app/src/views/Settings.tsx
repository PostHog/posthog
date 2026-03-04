import type { ExtensionContextValue } from '@stripe/ui-extension-sdk/context'
import { SettingsView } from '@stripe/ui-extension-sdk/ui'

import PostHogConnect from '../components/PostHogConnect'
import { getConstants } from '../constants'

const Settings = ({ environment }: ExtensionContextValue): JSX.Element => {
    return (
        <SettingsView>
            <PostHogConnect constants={getConstants(environment)} mode={environment.mode} />
        </SettingsView>
    )
}

export default Settings
