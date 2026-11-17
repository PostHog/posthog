// PROTOTYPE (ticket #385), throwaway. Mounted by the transactional list, the code email scene and the send detail
// scene when ?variant= is set in a PROTOTYPE=1 build. Renders the list (L1 to L3), the email page (D) or the send
// detail page (today, A).
import { useState } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { impactData } from './impactFixtures'
import { journeyData } from './journeyFixtures'
import { JourneyPrototypeSwitcher } from './JourneyPrototypeSwitcher'
import { listData } from './listFixtures'
import { journeyUrl, useEmailJourneyPrototype } from './useEmailJourneyPrototype'
import { VariantClickTimeline } from './VariantClickTimeline'
import { VariantImpactFunnel } from './VariantImpactFunnel'
import { VariantListColumns } from './VariantListColumns'
import { VariantListHighlights } from './VariantListHighlights'
import { VariantListPreview } from './VariantListPreview'
import { VariantToday } from './VariantToday'

const UNCHANGED = <p className="text-sm text-secondary m-0">Unchanged in this prototype.</p>

function ListPage(): JSX.Element {
    const { variant, journeyCase } = useEmailJourneyPrototype()
    const [tab, setTab] = useState('emails')
    const emails = listData(journeyCase)
    return (
        <SceneContent>
            <SceneTitleSection
                name="Transactional"
                description="Send emails from your code with one API call"
                resourceType={{ type: 'transactional' }}
            />
            <LemonTabs
                activeKey={tab}
                onChange={setTab}
                tabs={[
                    {
                        key: 'emails',
                        label: 'Emails',
                        content: (
                            <div className="@container">
                                {variant === 'L2' ? (
                                    <VariantListPreview emails={emails} />
                                ) : variant === 'L3' ? (
                                    <VariantListHighlights emails={emails} />
                                ) : (
                                    <VariantListColumns emails={emails} />
                                )}
                            </div>
                        ),
                    },
                    { key: 'log', label: 'Sends', content: UNCHANGED },
                    { key: 'metrics', label: 'Metrics', content: UNCHANGED },
                ]}
            />
            <JourneyPrototypeSwitcher />
        </SceneContent>
    )
}

function EmailPage(): JSX.Element {
    const { journeyCase, goal } = useEmailJourneyPrototype()
    const [tab, setTab] = useState('impact')
    const data = impactData(journeyCase, goal)
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
                                <VariantImpactFunnel data={data} />
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
    return surface === 'list' ? <ListPage /> : surface === 'email' ? <EmailPage /> : <SendPage />
}
