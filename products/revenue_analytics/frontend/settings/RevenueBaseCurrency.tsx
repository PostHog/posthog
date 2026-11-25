import { Text } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { BASE_CURRENCY_DESCRIPTION, BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function RevenueBaseCurrency(): JSX.Element {
    const quillSurface = useQuillSurface()

    const baseCurrency = (
        <AccessControlAction
            resourceType={AccessControlResourceType.RevenueAnalytics}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <BaseCurrency hideTitle={quillSurface} />
        </AccessControlAction>
    )

    if (!quillSurface) {
        return baseCurrency
    }

    // BaseCurrency keeps the description size that Settings shows, so this page sets the xs description that its
    // other sections use.
    return (
        <SceneSection title="Base currency">
            <Text size="xs" render={<p className="m-0 max-w-160" />}>
                {BASE_CURRENCY_DESCRIPTION}
            </Text>
            {baseCurrency}
        </SceneSection>
    )
}
