import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { IngestionLimitBanner } from '../components/IngestionLimitBanner'
import { RecordingsBlockBanner } from '../components/RecordingsBlockBanner'
import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { replayVisionEmptyState } from '../emptyState/replayVisionEmptyState'
import { ObservationSearch } from '../search/ObservationSearch'
import { CreateScannerButton } from './components/CreateScannerButton'
import { HighlightFeedTab } from './components/HighlightFeedTab'
import { QuillCreateScannerButton } from './components/QuillCreateScannerButton'
import { VisionHomeMenu } from './components/VisionHomeMenu'
import { VisionUsageTab } from './components/VisionUsageTab'
import { visionHomeLogic } from './visionHomeLogic'

export const scene: SceneExport = {
    component: ReplayScannersScene,
    logic: visionHomeLogic,
    productKey: ProductKey.REPLAY_VISION,
    emptyState: replayVisionEmptyState,
}

export function ReplayScannersScene(): JSX.Element {
    const { view, homeScanners } = useValues(visionHomeLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    // A project with no scanners has nothing to pick between, so its intro stands alone.
    const showMenu = homeScanners.length > 0 || view !== 'all'

    return (
        // Past three columns of cards the eye loses the row, so a very wide screen gets margins instead of a fourth.
        <SceneContent className="mx-auto w-full max-w-[100rem]">
            <SceneTitleSection
                name="Replay vision"
                description="Set up AI scanners that automatically analyze new session recordings as they come in. Each result emits a queryable event."
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <>
                        <ReplayVisionFeedbackButton />
                        {todayRailNav ? (
                            <QuillCreateScannerButton acceptedLabel="New scanner" dataAttr="vision-scanner-create" />
                        ) : (
                            <CreateScannerButton acceptedLabel="New scanner" dataAttr="vision-scanner-create" />
                        )}
                    </>
                }
            />

            <IngestionLimitBanner />
            <RecordingsBlockBanner />

            {showMenu && <VisionHomeMenu />}

            {view === 'search' ? (
                <ObservationSearch className="mt-2 w-4/5 mx-auto" />
            ) : view === 'usage' ? (
                <VisionUsageTab />
            ) : (
                // Keyed, so switching scanners starts each feed from its own first page.
                <HighlightFeedTab key={view} scannerId={view === 'all' ? undefined : view} />
            )}
        </SceneContent>
    )
}

export default ReplayScannersScene
