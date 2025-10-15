import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { campaignLogic } from './campaignLogic'
import { CampaignSceneLogicProps } from './campaignSceneLogic'

export const CampaignSceneHeader = (props: CampaignSceneLogicProps = {}): JSX.Element => {
    const logic = campaignLogic(props)
    const { campaign, campaignChanged, isCampaignSubmitting, campaignLoading, campaignHasErrors } = useValues(logic)
    const { saveCampaignPartial, submitCampaign, discardChanges, setCampaignValue } = useActions(logic)

    const isSavedCampaign = props.id && props.id !== 'new'

    return (
        <>
            <SceneTitleSection
                name={campaign?.name}
                description={campaign?.description}
                resourceType={{ type: 'messaging' }}
                canEdit
                onNameChange={(name) => setCampaignValue('name', name)}
                onDescriptionChange={(description) => setCampaignValue('description', description)}
                isLoading={campaignLoading}
                renameDebounceMs={200}
                actions={
                    <>
                        {isSavedCampaign && (
                            <>
                                <LemonButton
                                    type="primary"
                                    onClick={() =>
                                        saveCampaignPartial({
                                            status: campaign?.status === 'draft' ? 'active' : 'draft',
                                        })
                                    }
                                    size="small"
                                    loading={campaignLoading}
                                    disabledReason={campaignChanged ? 'Save changes first' : undefined}
                                >
                                    {campaign?.status === 'draft' ? 'Enable' : 'Disable'}
                                </LemonButton>
                            </>
                        )}

                        {isSavedCampaign && campaignChanged && (
                            <>
                                <LemonButton
                                    data-attr="discard-campaign-changes"
                                    type="secondary"
                                    onClick={() => discardChanges()}
                                    size="small"
                                >
                                    Discard changes
                                </LemonButton>
                            </>
                        )}

                        <LemonButton
                            type="primary"
                            size="small"
                            htmlType="submit"
                            form="campaign"
                            onClick={submitCampaign}
                            loading={isCampaignSubmitting}
                            disabledReason={
                                campaignHasErrors
                                    ? 'Some fields still need work'
                                    : campaignChanged
                                      ? undefined
                                      : 'No changes to save'
                            }
                        >
                            {props.id === 'new' ? 'Create' : 'Save'}
                        </LemonButton>
                    </>
                }
            />
        </>
    )
}
