// A one-shot hand-off that lets any surface kick off a task with the optimistic-open thread: the
// producer stores the message plus a thunk that creates and runs the task, then navigates to
// `/tasks/new`; `taskTrackerSceneLogic` consumes it there, seeds the thread with the message
// immediately, and provisions the task/run in the background (mirroring the composer's own submit).
//
// A plain module store rather than kea state: the producer's scene unmounts before the tasks scene
// mounts, and a kea-held value would reset in that gap unless someone held a mount across it.

export interface PendingTaskKickoff {
    /** The user's message — echoed into the thread the moment the tasks scene opens. */
    message: string
    /** Creates the task and starts its run; the scene attaches the returned ids to the seeded stream. */
    createAndRun: () => Promise<{ taskId: string; runId?: string }>
}

let pendingTaskKickoff: PendingTaskKickoff | null = null

export function setPendingTaskKickoff(kickoff: PendingTaskKickoff): void {
    pendingTaskKickoff = kickoff
}

/** Consume-once: returns and clears the pending kickoff, so a later `/tasks/new` visit never replays it. */
export function takePendingTaskKickoff(): PendingTaskKickoff | null {
    const kickoff = pendingTaskKickoff
    pendingTaskKickoff = null
    return kickoff
}
