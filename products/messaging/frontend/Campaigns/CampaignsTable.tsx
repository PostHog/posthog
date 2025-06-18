import { useActions, useMountedLogic, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { campaignsLogic } from './campaignsLogic'
import { HogFlow } from './Workflows/types'

export function CampaignsTable(): JSX.Element {
    useMountedLogic(campaignsLogic)
    const { campaigns, campaignsLoading } = useValues(campaignsLogic)
    const { deleteCampaign } = useActions(campaignsLogic)

    const columns: LemonTableColumns<HogFlow> = [
        {
            title: 'Name',
            render: (_, item) => {
                return (
                    <LemonTableLink to={urls.messagingCampaign(item.id)} title={item.name} description={item.status} />
                )
            },
        },
        {
            width: 0,
            render: function Render(_, campaign: HogFlow) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    data-attr="campaign-delete"
                                    fullWidth
                                    status="danger"
                                    onClick={() => deleteCampaign(campaign)}
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="campaigns-section">
            <LemonTable dataSource={campaigns} loading={campaignsLoading} columns={columns} />
        </div>
    )
}
