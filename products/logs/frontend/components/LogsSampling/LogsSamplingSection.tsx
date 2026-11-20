import { BindLogic } from 'kea'

import { Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LogsSamplingRulesSortableTable } from './LogsSamplingRulesSortableTable'
import { logsSamplingSectionLogic } from './logsSamplingSectionLogic'

export function LogsSamplingSection(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <BindLogic logic={logsSamplingSectionLogic} props={{}}>
                <div className="flex flex-col gap-3">
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Exclude noisy or sensitive lines before they are stored. Rules run top to bottom during
                        ingestion. Drag the handle on each row to change that order. Use Drop to remove matching lines,
                        or Rate limit to cap a service's volume.
                    </Text>
                    <LogsSamplingRulesSortableTable />
                </div>
            </BindLogic>
        )
    }

    return (
        <BindLogic logic={logsSamplingSectionLogic} props={{}}>
            <div className="space-y-3">
                <p className="text-muted m-0">
                    Exclude noisy or sensitive lines before they are stored. Rules run top to bottom during ingestion —
                    drag the handle on each row to change that order. Use Drop to remove matching lines, or Rate limit
                    to cap a service's volume.
                </p>
                <LogsSamplingRulesSortableTable />
            </div>
        </BindLogic>
    )
}
