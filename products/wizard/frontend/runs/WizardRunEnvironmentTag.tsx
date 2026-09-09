import { IconCloud, IconLaptop } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { RunEnvironmentEnumApi } from '../generated/api.schemas'

export function WizardRunEnvironmentTag({ environment }: { environment: RunEnvironmentEnumApi }): JSX.Element {
    return (
        <LemonTag
            type={environment === 'cloud' ? 'info' : 'default'}
            size="medium"
            icon={environment === 'cloud' ? <IconCloud /> : <IconLaptop />}
        >
            {environment === 'cloud' ? 'Cloud' : 'Local'}
        </LemonTag>
    )
}
