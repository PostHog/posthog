import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { socialSignalsSettingsLogic } from '../logics/socialSignalsSettingsLogic'

export const scene: SceneExport = {
    component: SocialSignalsSettingsScene,
    logic: socialSignalsSettingsLogic,
}

export function SocialSignalsSettingsScene(): JSX.Element {
    const { octolensSource, sourcesLoading, sourcesUpdating, webhookUrl } = useValues(socialSignalsSettingsLogic)
    const { ensureOctolensSource, rotateToken } = useActions(socialSignalsSettingsLogic)

    if (sourcesLoading && !octolensSource) {
        return (
            <SceneContent>
                <SceneTitleSection name="Social signals settings" resourceType={{ type: 'social_signals' }} />
                <LemonSkeleton className="h-32 w-full max-w-2xl" />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection name="Social signals settings" resourceType={{ type: 'social_signals' }} />
            <div className="max-w-2xl space-y-4">
                <p className="text-muted">
                    Configure ingestion sources for social mentions. Octolens is the only built-in source today —
                    additional ingestion sources will appear here as they ship.
                </p>

                <div className="rounded border p-4 space-y-3">
                    <h3 className="font-semibold">Octolens webhook</h3>
                    {octolensSource ? (
                        <>
                            <p className="text-sm">
                                Paste this URL into your{' '}
                                <Link to="https://octolens.com" target="_blank" rel="noopener noreferrer">
                                    Octolens
                                </Link>{' '}
                                webhook destination settings. The token is the credential — keep it private.
                            </p>
                            <code className="block break-all bg-bg-3000 p-2 rounded text-xs">{webhookUrl}</code>
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={rotateToken}
                                loading={sourcesUpdating}
                                disabledReason={sourcesUpdating ? 'Rotating…' : undefined}
                            >
                                Rotate token
                            </LemonButton>
                        </>
                    ) : (
                        <LemonButton
                            type="primary"
                            onClick={ensureOctolensSource}
                            loading={sourcesUpdating}
                            disabledReason={sourcesUpdating ? 'Creating…' : undefined}
                        >
                            Generate Octolens webhook URL
                        </LemonButton>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}

export default SocialSignalsSettingsScene
