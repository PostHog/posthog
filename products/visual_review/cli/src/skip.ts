// Outside index.ts, which runs the CLI on import, so a test can import it.
import { VisualReviewClient, type NoRunNeededInput } from './client.js'
import { log } from './outcome.js'

// Any answer of the backend exits 0, also when it posted nothing. A failed request exits 1, so the job
// shows the missing status and a re-run of it reports again.
export async function reportNoRunNeeded(client: VisualReviewClient, input: NoRunNeededInput): Promise<number> {
    const commit = input.commit_sha.slice(0, 10)
    try {
        const result = await client.reportNoRunNeeded(input)
        log(`No ${input.run_type} run needed for ${commit}: ${result.detail}`)
        return 0
    } catch (error) {
        log(
            `Could not report that ${commit} needs no ${input.run_type} run: ${error instanceof Error ? error.message : error}`
        )
        return 1
    }
}
