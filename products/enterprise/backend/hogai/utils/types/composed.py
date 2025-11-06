"""
This module contains types that are composed from the different graphs.
This is used to avoid circular imports.
"""

from products.enterprise.backend.hogai.graph.deep_research.types import (
    DeepResearchNodeName,
    DeepResearchState,
    PartialDeepResearchState,
)
from products.enterprise.backend.hogai.graph.taxonomy.types import TaxonomyAgentState, TaxonomyNodeName
from products.enterprise.backend.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState

MaxNodeName = AssistantNodeName | TaxonomyNodeName | DeepResearchNodeName

MaxGraphState = AssistantState | TaxonomyAgentState | DeepResearchState

MaxPartialGraphState = PartialAssistantState | TaxonomyAgentState | PartialDeepResearchState

# States that are used in the Assistant class
AssistantMaxGraphState = AssistantState | DeepResearchState
AssistantMaxPartialGraphState = PartialAssistantState | PartialDeepResearchState
