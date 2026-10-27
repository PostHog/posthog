import { useActions, useValues } from 'kea'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { tagsModel } from '~/models/tagsModel'

import type { HogFlowConversionApi } from 'products/workflows/frontend/generated/api.schemas'

import { ConversionGoalEditor } from '../../Workflows/hogflows/steps/components/ConversionGoalEditor'
import { DEFAULT_BROADCAST_CONVERSION, broadcastWizardLogic } from '../broadcastWizardLogic'

export function BroadcastGoalStep(): JSX.Element {
    const { goalEnabled, conversion, stepValidationErrors, tags } = useValues(broadcastWizardLogic)
    const { setGoalEnabled, setConversion, setTags } = useActions(broadcastWizardLogic)
    const { tags: allTags } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)

    return (
        <div className="flex flex-col gap-4">
            <div>
                <h2 className="m-0 text-xl font-semibold">Do you want to measure a conversion goal?</h2>
                <p className="m-0 text-secondary">
                    A goal counts recipients who do something after receiving the email, like signing up or making a
                    purchase.
                </p>
            </div>

            <LemonRadio
                value={goalEnabled ? 'goal' : 'none'}
                onChange={(value) => setGoalEnabled(value === 'goal')}
                options={[
                    { value: 'none', label: 'No goal' },
                    { value: 'goal', label: 'Set a conversion goal' },
                ]}
            />

            {goalEnabled && (
                <div className="flex flex-col gap-2">
                    <ConversionGoalEditor
                        conversion={conversion}
                        onChange={(newConversion) =>
                            setConversion({
                                ...DEFAULT_BROADCAST_CONVERSION,
                                ...newConversion,
                            } as HogFlowConversionApi)
                        }
                        pageKey="broadcast-wizard-goal"
                    />
                    <p className="m-0 text-xs text-muted">
                        Conversions are counted within 7 days of a person receiving the broadcast.
                    </p>
                    {stepValidationErrors.goal.map((error) => (
                        <div key={error} className="text-danger text-xs">
                            {error}
                        </div>
                    ))}
                </div>
            )}

            <div className="flex flex-col gap-2">
                <div>
                    <h2 className="m-0 text-xl font-semibold">Tags</h2>
                    <p className="m-0 text-secondary">
                        Group related broadcasts, like repeated sends in one campaign. You can filter the broadcasts
                        list by tag.
                    </p>
                </div>
                <ObjectTags
                    tags={tags}
                    onChange={setTags}
                    onEdit={loadTagsIfNeeded}
                    saving={false}
                    tagsAvailable={allTags.filter((tag: string) => !tags.includes(tag))}
                    data-attr="broadcast-wizard-tags"
                />
            </div>
        </div>
    )
}
