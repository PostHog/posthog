import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AWS_REGIONS } from '../awsRegions'
import { logsSourcesLogic } from '../logsSourcesLogic'

export function DetailsStep(): JSX.Element {
    const { draftName, draftRegion } = useValues(logsSourcesLogic)
    const { setDraftName, setDraftRegion } = useActions(logsSourcesLogic)
    return (
        <div className="space-y-4">
            <p className="m-0 text-secondary">
                Give the source a name and pick the AWS region of the log groups you want to stream. One source covers
                one region.
            </p>
            <LemonField.Pure label="Name">
                <LemonInput
                    value={draftName}
                    onChange={setDraftName}
                    placeholder="Production account"
                    autoFocus
                    data-attr="logs-source-name"
                />
            </LemonField.Pure>
            <LemonField.Pure label="AWS region">
                <LemonSelect
                    value={draftRegion}
                    onChange={(value) => value && setDraftRegion(value)}
                    options={AWS_REGIONS}
                    fullWidth
                    data-attr="logs-source-region"
                />
            </LemonField.Pure>
        </div>
    )
}
