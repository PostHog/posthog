import { LemonBanner } from '@posthog/lemon-ui'

import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

const LOGS_TRANSFORMATIONS_LOGIC_KEY = 'logs-transformations'

export function LogsTransformations(): JSX.Element {
    return (
        <SceneContent>
            <LemonBanner type="info" dismissKey="logs-transformations-beta-banner" className="mb-3">
                Transformations run on every log record as it is ingested. Use them to mutate, redact, or drop records.
                They run in order, and a transformation that returns null drops the record.
            </LemonBanner>
            <SceneSection title="Transformations" description="Modify or drop log records as they are ingested.">
                <HogFunctionList logicKey={LOGS_TRANSFORMATIONS_LOGIC_KEY} type="transformation_log" />
            </SceneSection>
            <SceneDivider />
            <SceneSection title="Create a new transformation">
                <HogFunctionTemplateList type="transformation_log" hideComingSoonByDefault />
            </SceneSection>
        </SceneContent>
    )
}
