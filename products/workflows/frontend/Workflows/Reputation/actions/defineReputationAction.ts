import type { ReputationActionContext } from './reputationActionContext'
import type { ReputationActionRank } from './reputationActionRanking'
import type {
    ReputationAction,
    ReputationActionCta,
    ReputationActionKind,
    ReputationDocsLink,
} from './reputationActionTypes'

interface ReputationActionContent {
    /** Unique among the rows of one action. The list makes a repeat unique on its own. */
    key: string
    rank: ReputationActionRank
    blocksSending?: boolean
    title: string
    description: string
    docsLink?: ReputationDocsLink
}

/**
 * One kind of item the action list can show. `detect` decides when it shows and returns one
 * match per row. `content` and `cta` turn a match into what the row says and what its button does.
 */
interface ReputationActionDefinition<Match> {
    kind: ReputationActionKind
    detect: (context: ReputationActionContext) => readonly Match[]
    content: (match: Match, context: ReputationActionContext) => ReputationActionContent
    /** Leave out when no page in PostHog helps with the item. */
    cta?: (match: Match, context: ReputationActionContext) => ReputationActionCta
}

export interface RankedReputationAction extends ReputationAction {
    rank: ReputationActionRank
}

/** A registered action. The match type stays inside, so the registry can hold every action in one list. */
export interface RegisteredReputationAction {
    kind: ReputationActionKind
    build: (context: ReputationActionContext) => RankedReputationAction[]
}

export function defineReputationAction<Match>(
    definition: ReputationActionDefinition<Match>
): RegisteredReputationAction {
    return {
        kind: definition.kind,
        build: (context) =>
            definition.detect(context).map((match) => {
                const { rank, blocksSending, ...content } = definition.content(match, context)
                return {
                    ...content,
                    kind: definition.kind,
                    severity: rank.severity,
                    blocksSending: blocksSending ?? false,
                    cta: definition.cta?.(match, context),
                    rank,
                }
            }),
    }
}
