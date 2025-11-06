import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { LemonButton, LemonCheckbox, LemonInput, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { syntheticMonitorLogic } from './syntheticMonitorLogic'
import { SyntheticMonitoringRegion } from './types'

export const scene: SceneExport = {
    component: SyntheticMonitor,
    logic: syntheticMonitorLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id || 'new' }),
}

const READABLE_SYNTHETIC_MONITORING_REGIONS: Record<SyntheticMonitoringRegion, string> = {
    [SyntheticMonitoringRegion.US_EAST_1]: 'US East (N. Virginia)',
    [SyntheticMonitoringRegion.US_WEST_2]: 'US West (Oregon)',
    [SyntheticMonitoringRegion.EU_WEST_1]: 'EU West (Ireland)',
    [SyntheticMonitoringRegion.EU_CENTRAL_1]: 'EU Central (Frankfurt)',
    [SyntheticMonitoringRegion.AP_SOUTHEAST_1]: 'Asia Pacific (Singapore)',
    [SyntheticMonitoringRegion.AP_NORTHEAST_1]: 'Asia Pacific (Tokyo)',
}

export function SyntheticMonitor(): JSX.Element {
    const { monitor, isMonitorFormSubmitting } = useValues(syntheticMonitorLogic)
    const { submitMonitorForm } = useActions(syntheticMonitorLogic)

    const isNew = !monitor?.id

    return (
        <Form logic={syntheticMonitorLogic} formKey="monitorForm" enableFormOnSubmit>
            <SceneContent>
                <SceneTitleSection
                    name={isNew ? 'New monitor' : monitor?.name || 'Edit monitor'}
                    resourceType={{ type: 'synthetic_monitor' }}
                    description={
                        isNew
                            ? 'Configure an HTTP endpoint monitor to track uptime, latency, and get alerts when issues occur'
                            : null
                    }
                    actions={
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => router.actions.push(urls.syntheticMonitoring())}
                                disabled={isMonitorFormSubmitting}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                htmlType="submit"
                                loading={isMonitorFormSubmitting}
                                onClick={submitMonitorForm}
                            >
                                {isNew ? 'Create monitor' : 'Save'}
                            </LemonButton>
                        </>
                    }
                    forceBackTo={{
                        name: 'Synthetic monitoring',
                        path: urls.syntheticMonitoring(),
                        key: 'synthetic-monitoring',
                    }}
                />
                <SceneDivider />
                <SceneSection title="Monitor configuration" description="Configure the HTTP endpoint to monitor">
                    <div className="space-y-4">
                        <LemonField name="enabled" label="">
                            {({ value, onChange }) => (
                                <LemonCheckbox checked={value} onChange={onChange} label="Monitor enabled" />
                            )}
                        </LemonField>

                        <LemonField name="name" label="Name">
                            <LemonInput placeholder="My API endpoint" />
                        </LemonField>

                        <LemonField name="url" label="URL">
                            <LemonInput placeholder="https://api.example.com/health" />
                        </LemonField>

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                            <LemonField name="method" label="HTTP Method">
                                <LemonSelect
                                    options={[
                                        { label: 'GET', value: 'GET' },
                                        { label: 'POST', value: 'POST' },
                                        { label: 'PUT', value: 'PUT' },
                                        { label: 'PATCH', value: 'PATCH' },
                                        { label: 'DELETE', value: 'DELETE' },
                                        { label: 'HEAD', value: 'HEAD' },
                                    ]}
                                />
                            </LemonField>

                            <LemonField name="expected_status_code" label="Expected status code">
                                <LemonInput type="number" placeholder="200" />
                            </LemonField>

                            <LemonField name="frequency_minutes" label="Check frequency">
                                <LemonSelect
                                    options={[
                                        { label: 'Every 1 minute', value: 1 },
                                        { label: 'Every 5 minutes', value: 5 },
                                        { label: 'Every 15 minutes', value: 15 },
                                        { label: 'Every 30 minutes', value: 30 },
                                        { label: 'Every 60 minutes', value: 60 },
                                    ]}
                                />
                            </LemonField>

                            <LemonField name="timeout_seconds" label="Timeout (seconds)">
                                <LemonInput type="number" placeholder="30" />
                            </LemonField>
                        </div>

                        <LemonField
                            name="body"
                            label="Request body"
                            showOptional
                            help="Optional JSON body for POST/PUT requests"
                        >
                            <LemonInput placeholder='{"key": "value"}' />
                        </LemonField>
                    </div>
                </SceneSection>
                <SceneDivider />
                <SceneSection title="Regions" description="Select AWS regions to run checks from">
                    <LemonField name="regions" label="">
                        <LemonInputSelect
                            mode="multiple"
                            placeholder="Select regions"
                            options={Object.entries(SyntheticMonitoringRegion).map(([key, value]) => ({
                                label: READABLE_SYNTHETIC_MONITORING_REGIONS[value],
                                key,
                                value,
                            }))}
                        />
                    </LemonField>
                </SceneSection>
            </SceneContent>
        </Form>
    )
}
