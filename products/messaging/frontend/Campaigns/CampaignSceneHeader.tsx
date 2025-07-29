import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { useValues, useActions } from 'kea'
import { campaignLogic } from './campaignLogic'
import { CampaignSceneLogicProps } from './campaignSceneLogic'

export const CampaignSceneHeader = (props: CampaignSceneLogicProps = {}): JSX.Element => {
    const logic = campaignLogic(props)
    const { campaign, campaignChanged, isCampaignSubmitting, campaignLoading, isCampaignValid } = useValues(logic)
    const { saveCampaign, submitCampaign, discardChanges } = useActions(logic)

    const isSavedCampaign = props.id && props.id !== 'new'

    return (
        <PageHeader
            buttons={
                <>
                    {isSavedCampaign && (
                        <>
                            <LemonButton
                                type="primary"
                                onClick={() =>
                                    saveCampaign({
                                        status: campaign?.status === 'draft' ? 'active' : 'draft',
                                    })
                                }
                                loading={campaignLoading}
                                disabledReason={campaignChanged ? 'Save changes first' : undefined}
                            >
                                {campaign?.status === 'draft' ? 'Enable' : 'Disable'}
                            </LemonButton>
                            <LemonDivider vertical />
                        </>
                    )}

                    {isSavedCampaign && campaignChanged && (
                        <>
                            <LemonButton
                                data-attr="discard-campaign-changes"
                                type="secondary"
                                onClick={() => discardChanges()}
                            >
                                Discard changes
                            </LemonButton>
                        </>
                    )}

                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        form="campaign"
                        onClick={submitCampaign}
                        loading={isCampaignSubmitting}
                        disabledReason={
                            !isCampaignValid
                                ? 'Fill in all required fields'
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
    )
}
