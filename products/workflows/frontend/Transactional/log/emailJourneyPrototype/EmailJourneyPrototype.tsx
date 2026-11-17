// PROTOTYPE (ticket #385), throwaway. Mounted by the send detail scene when ?variant= is set in a PROTOTYPE=1 build.
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { journeyData } from './journeyFixtures'
import { JourneyPrototypeSwitcher } from './JourneyPrototypeSwitcher'
import { useEmailJourneyPrototype } from './useEmailJourneyPrototype'
import { VariantAnnotatedEmail } from './VariantAnnotatedEmail'
import { VariantClickTimeline } from './VariantClickTimeline'
import { VariantPersonStory } from './VariantPersonStory'
import { VariantToday } from './VariantToday'

export function EmailJourneyPrototype(): JSX.Element {
    const { variant, journeyCase } = useEmailJourneyPrototype()
    const data = journeyData(journeyCase)
    return (
        <SceneContent>
            <SceneTitleSection
                name={data.recipient}
                description={data.subject}
                resourceType={{ type: 'transactional' }}
                actions={
                    <LemonButton type="secondary" size="small" to={urls.transactionalLog()}>
                        Open email
                    </LemonButton>
                }
            />
            {variant === 'A' ? (
                <VariantClickTimeline data={data} />
            ) : variant === 'B' ? (
                <VariantPersonStory data={data} />
            ) : variant === 'C' ? (
                <VariantAnnotatedEmail data={data} />
            ) : (
                <VariantToday data={data} />
            )}
            <JourneyPrototypeSwitcher />
        </SceneContent>
    )
}
