import { IconCloud, IconLaptop } from '@posthog/icons'
import { Badge } from '@posthog/quill-primitives'

import type { RunEnvironmentEnumApi } from '../generated/api.schemas'

export function WizardRunEnvironmentTag({ environment }: { environment: RunEnvironmentEnumApi }): JSX.Element {
    return (
        <Badge variant={environment === 'cloud' ? 'info' : 'default'}>
            {environment === 'cloud' ? <IconCloud /> : <IconLaptop />}
            {environment === 'cloud' ? 'Cloud' : 'Local'}
        </Badge>
    )
}
