import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { InsightPickerEndpointModal } from '../InsightPickerEndpointModal'
import { OverlayForNewEndpointMenu } from '../newEndpointMenu'

/**
 * The endpoints scene's own "New" button, reproduced for the setup empty state.
 * Both routes into endpoint creation live on that button, and the insight-based one
 * has no URL of its own, so a first-run screen offering only the SQL editor would
 * make the insight route unreachable for the projects most likely to want it.
 */
export function CreateFirstEndpointButton(): JSX.Element {
    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.Endpoint}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton
                    type="primary"
                    to={urls.sqlEditor({ source: 'endpoint' })}
                    sideAction={{
                        dropdown: {
                            placement: 'bottom-end',
                            className: 'new-endpoint-overlay',
                            actionable: true,
                            overlay: <OverlayForNewEndpointMenu />,
                        },
                        'data-attr': 'new-endpoint-dropdown',
                    }}
                    data-attr="new-endpoint-button"
                    icon={<IconPlusSmall />}
                    className="self-start"
                >
                    Create your first endpoint
                </LemonButton>
            </AccessControlAction>
            {/* The scene mounts this modal, and the gate renders in place of the scene, so without
                it here the dropdown's insight option would open nothing. */}
            <InsightPickerEndpointModal />
        </>
    )
}
