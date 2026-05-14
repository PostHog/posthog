// Types for the Semantic Layer Proposals inbox prototype.
//
// This is a hackathon UI mockup — every shape here is a frontend-only fixture
// so we can iterate on the inbox UX without committing to a backend schema.

export type ProposalKind =
    | 'new_definition'
    | 'drift'
    | 'duplicate'
    | 'schema_sync'
    | 'relationship'
    | 'metadata'
    | 'question'

export type ProposalStatus = 'open' | 'approved' | 'rejected' | 'snoozed'

export type DefinitionKind = 'metric' | 'entity' | 'dimension'

export interface Provenance {
    source: string
    detail?: string
}

export interface ProposedDefinition {
    name: string
    kind: DefinitionKind
    description: string
    formulaPlainEnglish?: string
    formulaSql?: string
    suggestedDimensions?: string[]
    suggestedOwner?: string
    entity?: string
}

export interface DiffField {
    field: string
    before: string
    after: string
}

export interface ImpactSummary {
    insights?: number
    dashboards?: number
    notebooks?: number
    consumers?: string[]
}

export interface BaseProposal {
    id: string
    kind: ProposalKind
    title: string
    summary: string
    ageHours: number
    confidence: number
    status: ProposalStatus
    provenance: Provenance[]
    impact?: ImpactSummary
    suggestedReviewers?: string[]
    rejectionReason?: string
}

export interface NewDefinitionProposal extends BaseProposal {
    kind: 'new_definition'
    definition: ProposedDefinition
}

export interface DriftProposal extends BaseProposal {
    kind: 'drift'
    targetDefinition: string
    targetKind: DefinitionKind
    diff: DiffField[]
    triggerEvent: string
}

export interface DuplicateProposal extends BaseProposal {
    kind: 'duplicate'
    candidates: {
        id: string
        name: string
        description: string
        owner?: string
        usage: number
    }[]
    recommendedCanonicalIndex: number
}

export interface SchemaSyncProposal extends BaseProposal {
    kind: 'schema_sync'
    sourceTable: string
    addedColumns: {
        column: string
        type: string
        suggestedRole: 'dimension' | 'measure' | 'foreign_key'
        preselected: boolean
    }[]
}

export interface RelationshipProposal extends BaseProposal {
    kind: 'relationship'
    leftSide: { entity: string; field: string }
    rightSide: { entity: string; field: string }
    relationshipType: 'one_to_one' | 'one_to_many' | 'many_to_many'
    sampleMatches: { left: string; right: string }[]
}

export interface MetadataProposal extends BaseProposal {
    kind: 'metadata'
    targetDefinition: string
    targetKind: DefinitionKind
    changes: DiffField[]
}

export interface QuestionProposal extends BaseProposal {
    kind: 'question'
    question: string
    options?: { id: string; label: string; rationale: string }[]
    allowFreeform?: boolean
}

export type Proposal =
    | NewDefinitionProposal
    | DriftProposal
    | DuplicateProposal
    | SchemaSyncProposal
    | RelationshipProposal
    | MetadataProposal
    | QuestionProposal

export interface ProposalCategory {
    key: ProposalKind | 'all'
    label: string
    iconLabel: string
    description: string
}

export const PROPOSAL_CATEGORIES: ProposalCategory[] = [
    {
        key: 'all',
        label: 'Inbox',
        iconLabel: '∗',
        description: 'Everything waiting on review',
    },
    {
        key: 'new_definition',
        label: 'New definitions',
        iconLabel: '⊕',
        description: 'Entities, metrics and dimensions the agent discovered',
    },
    {
        key: 'drift',
        label: 'Drift',
        iconLabel: '⚠',
        description: 'Definitions that may be stale after upstream changes',
    },
    {
        key: 'duplicate',
        label: 'Duplicates',
        iconLabel: '⇆',
        description: 'Likely-duplicate definitions to merge',
    },
    {
        key: 'schema_sync',
        label: 'Schema sync',
        iconLabel: '⇨',
        description: 'New columns in connected sources',
    },
    {
        key: 'relationship',
        label: 'Relationships',
        iconLabel: '↔',
        description: 'Detected joins across entities',
    },
    {
        key: 'metadata',
        label: 'Metadata',
        iconLabel: '✎',
        description: 'Suggested description, synonym and owner improvements',
    },
    {
        key: 'question',
        label: 'Questions',
        iconLabel: '?',
        description: 'Agent needs your input to proceed',
    },
]

export const KIND_LABELS: Record<ProposalKind, string> = {
    new_definition: 'New definition',
    drift: 'Drift alert',
    duplicate: 'Merge duplicates',
    schema_sync: 'Schema sync',
    relationship: 'Relationship',
    metadata: 'Metadata',
    question: 'Question',
}
