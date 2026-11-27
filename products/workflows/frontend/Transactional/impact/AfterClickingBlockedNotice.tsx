import { AfterClickingNotice } from './AfterClickingNotice'
import type { ScanBlockedState } from './afterClickingScanLogic'

export function AfterClickingBlockedNotice({ state }: { state: ScanBlockedState }): JSX.Element {
    switch (state.kind) {
        case 'not-main-environment':
            return (
                <AfterClickingNotice title="Replay vision scans run in the main environment">
                    <span className="text-secondary text-sm">
                        Replay vision can only scan sessions recorded in a project's main environment, so it can't scan
                        the sessions from this environment.
                    </span>
                </AfterClickingNotice>
            )
        case 'no-access':
            return (
                <AfterClickingNotice title="You can't ask Replay vision about these sessions">
                    <span className="text-secondary text-sm">{state.reason}</span>
                </AfterClickingNotice>
            )
        case 'link-tagging-off':
            return (
                <AfterClickingNotice title="Link tracking is off">
                    <span className="text-secondary text-sm">
                        Replay vision finds the sessions this email starts through the tag on its links. Turn on link
                        tracking to tag the links of new sends.
                    </span>
                </AfterClickingNotice>
            )
        case 'sensitive-email':
            return (
                <AfterClickingNotice title="This email's sessions can't be found">
                    <span className="text-secondary text-sm">
                        This email is always sensitive, so its links carry no tag that ties a session to it.
                    </span>
                </AfterClickingNotice>
            )
    }
}
