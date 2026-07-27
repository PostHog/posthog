import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTextArea } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BetStateTag } from './BetStateTag'
import { BetRecord, foundryLogic } from './foundryLogic'

export const scene: SceneExport = {
    component: FoundryScene,
    logic: foundryLogic,
    productKey: ProductKey.FOUNDRY,
}

export function FoundryScene(): JSX.Element {
    const { bets, betsLoading, isNewBetModalOpen, isNewBetSubmitting, newBet } = useValues(foundryLogic)
    const { showNewBetModal, hideNewBetModal, setNewBetField, submitNewBet } = useActions(foundryLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Foundry"
                description="A portfolio of bets: hypotheses shipped behind flags and verified by the market."
                resourceType={{ type: 'experiment' }}
                actions={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        size="small"
                        onClick={showNewBetModal}
                        data-attr="foundry-new-bet"
                    >
                        New bet
                    </LemonButton>
                }
            />
            <LemonTable
                loading={betsLoading}
                dataSource={bets}
                emptyState="No bets yet. Place one and let the market decide."
                columns={[
                    {
                        title: 'Bet',
                        key: 'slug',
                        render: (_, bet: BetRecord) => (
                            <LemonTableLink
                                to={urls.foundryBet(bet.id)}
                                title={bet.slug}
                                description={bet.hypothesis}
                            />
                        ),
                    },
                    {
                        title: 'State',
                        key: 'state',
                        render: (_, bet: BetRecord) => <BetStateTag bet={bet} />,
                    },
                    {
                        title: 'Iteration',
                        key: 'iteration',
                        render: (_, bet: BetRecord) => <>{bet.iteration}</>,
                    },
                    {
                        title: 'Budget (USD)',
                        key: 'budget',
                        render: (_, bet: BetRecord) => <>{bet.budget?.usd ?? '—'}</>,
                    },
                    {
                        title: 'Created',
                        key: 'created_at',
                        render: (_, bet: BetRecord) => <TZLabel time={bet.created_at} />,
                    },
                ]}
            />
            <LemonModal
                isOpen={isNewBetModalOpen}
                onClose={hideNewBetModal}
                title="New bet"
                description="A falsifiable hypothesis with a budget, one success metric, and guardrails."
                footer={
                    <>
                        <LemonButton
                            onClick={hideNewBetModal}
                            disabledReason={isNewBetSubmitting ? 'Submitting…' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            loading={isNewBetSubmitting}
                            onClick={submitNewBet}
                            data-attr="foundry-bet-create"
                        >
                            Create bet
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-2">
                    <LemonField.Pure label="Slug">
                        <LemonInput
                            placeholder="checkout-friction"
                            value={newBet.slug}
                            onChange={(value) => setNewBetField('slug', value)}
                            data-attr="foundry-bet-slug"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Hypothesis">
                        <LemonTextArea
                            placeholder="Reducing checkout steps from 3 to 1 raises purchase conversion"
                            value={newBet.hypothesis}
                            onChange={(value) => setNewBetField('hypothesis', value)}
                            data-attr="foundry-bet-hypothesis"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Success metric">
                        <LemonInput
                            placeholder="purchase conversion rate"
                            value={newBet.metric_name}
                            onChange={(value) => setNewBetField('metric_name', value)}
                            data-attr="foundry-bet-metric"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Target">
                        <LemonInput
                            placeholder="+10%"
                            value={newBet.metric_target}
                            onChange={(value) => setNewBetField('metric_target', value)}
                            data-attr="foundry-bet-target"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Guardrail">
                        <LemonInput
                            placeholder="error rate must not rise"
                            value={newBet.guardrail}
                            onChange={(value) => setNewBetField('guardrail', value)}
                            data-attr="foundry-bet-guardrail"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Budget (USD)">
                        <LemonInput
                            type="number"
                            value={newBet.budget_usd}
                            onChange={(value) => setNewBetField('budget_usd', value)}
                            data-attr="foundry-bet-budget"
                        />
                    </LemonField.Pure>
                </div>
            </LemonModal>
        </SceneContent>
    )
}
