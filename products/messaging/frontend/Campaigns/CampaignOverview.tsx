import '@xyflow/react/dist/style.css'

import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { campaignLogic, CampaignLogicProps } from './campaignLogic'

export function CampaignOverview({ id }: CampaignLogicProps = {}): JSX.Element {
    const logic = campaignLogic({ id })
    const { campaignLoading } = useValues(logic)

    return (
        <div className="flex flex-col gap-4">
            <Form logic={campaignLogic} formKey="campaign">
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="flex-1 self-start p-3 space-y-2 rounded border min-w-100 bg-surface-primary">
                        <LemonField name="name" label="Name">
                            <LemonInput disabled={campaignLoading} />
                        </LemonField>

                        <LemonField
                            name="description"
                            label="Description"
                            info="Add a description to share context with other team members"
                        >
                            <LemonInput disabled={campaignLoading} />
                        </LemonField>
                    </div>
                </div>
            </Form>
        </div>
    )
}
