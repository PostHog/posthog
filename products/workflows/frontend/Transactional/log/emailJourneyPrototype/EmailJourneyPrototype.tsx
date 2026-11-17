// PROTOTYPE (ticket #385), throwaway. Mounted by the code email scene and the send detail scene when ?variant= is
// set in a PROTOTYPE=1 build. Renders the email page (variants D, E, F) or the send detail page (today, A).
import { useState } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { impactData } from './impactFixtures'
import { journeyData } from './journeyFixtures'
import { JourneyPrototypeSwitcher } from './JourneyPrototypeSwitcher'
import { journeyUrl, useEmailJourneyPrototype } from './useEmailJourneyPrototype'
import { VariantClickTimeline } from './VariantClickTimeline'
import { VariantImpactFindings } from './VariantImpactFindings'
import { VariantImpactFunnel } from './VariantImpactFunnel'
import { VariantImpactHeatmap } from './VariantImpactHeatmap'
import { VariantToday } from './VariantToday'

const UNCHANGED = <p className="text-sm text-secondary m-0">Unchanged in this prototype. Go back to Impact.</p>

function EmailPage(): JSX.Element {
    const { variant, journeyCase } = useEmailJourneyPrototype()
    const [tab, setTab] = useState('impact')
    const data = impactData(journeyCase)
    return (
        <SceneContent>
            <SceneTitleSection
                name={data.key}
                description={`"${data.subject}", sent by your code from ${data.sendingDomain}`}
                resourceType={{ type: 'transactional' }}
            />
            <LemonTabs
                activeKey={tab}
                onChange={setTab}
                tabs={[
                    {
                        key: 'impact',
                        label: (
                            <span className="flex items-center gap-1">
                                Impact <LemonTag type="highlight">New</LemonTag>
                            </span>
                        ),
                        content: (
                            <div className="@container">
                                {variant === 'E' ? (
                                    <VariantImpactFindings data={data} />
                                ) : variant === 'F' ? (
                                    <VariantImpactHeatmap data={data} />
                                ) : (
                                    <VariantImpactFunnel data={data} />
                                )}
                            </div>
                        ),
                    },
                    { key: 'metrics', label: 'Metrics', content: UNCHANGED },
                    { key: 'sends', label: 'Sends', content: UNCHANGED },
                    { key: 'runs', label: 'Run logs', content: UNCHANGED },
                    { key: 'api', label: 'API', content: UNCHANGED },
                ]}
            />
            <JourneyPrototypeSwitcher />
        </SceneContent>
    )
}

function SendPage(): JSX.Element {
    const { variant, journeyCase } = useEmailJourneyPrototype()
    const data = journeyData(journeyCase)
    return (
        <SceneContent>
            <SceneTitleSection
                name={data.recipient}
                description={data.subject}
                resourceType={{ type: 'transactional' }}
                actions={
                    <LemonButton type="secondary" size="small" to={journeyUrl('D')}>
                        Open email
                    </LemonButton>
                }
            />
            {variant === 'A' ? <VariantClickTimeline data={data} /> : <VariantToday data={data} />}
            <JourneyPrototypeSwitcher />
        </SceneContent>
    )
}

export function EmailJourneyPrototype(): JSX.Element {
    const { surface } = useEmailJourneyPrototype()
    return surface === 'email' ? <EmailPage /> : <SendPage />
}
