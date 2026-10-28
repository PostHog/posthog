from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "papers": {
        "description": "Academic papers that match the configured search query.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "paperId": "The primary Semantic Scholar identifier for the paper.",
            "corpusId": "The numeric identifier used in Semantic Scholar datasets.",
            "externalIds": "Identifiers from other sources, such as DOI and arXiv.",
            "title": "The title of the paper.",
            "abstract": "The abstract, when available for distribution through the API.",
            "url": "The page for the paper on Semantic Scholar.",
            "year": "The year of publication.",
            "publicationDate": "The date of publication, when known.",
            "citationCount": "The number of papers that cite this paper.",
            "referenceCount": "The number of papers cited by this paper.",
            "authors": "Authors of the paper, with their Semantic Scholar identifiers.",
            "venue": "The journal or conference that published the paper.",
            "isOpenAccess": "Whether the paper has open access.",
        },
    },
    "citations": {
        "description": "Papers that cite papers in the configured search results. Unresolved paper links are excluded.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "paper_id": "The identifier of the paper in the search results.",
            "related_paper_id": "The identifier of the paper that cites the search result.",
            "citingPaper": "Metadata for the paper that contains the citation.",
            "contexts": "Text around the citation in the citing paper.",
            "intents": "The classified purposes of the citation.",
            "isInfluential": "Whether Semantic Scholar classifies the citation as influential.",
        },
    },
    "references": {
        "description": "Papers cited by papers in the configured search results. Unresolved paper links are excluded.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "paper_id": "The identifier of the paper in the search results.",
            "related_paper_id": "The identifier of the paper cited by the search result.",
            "citedPaper": "Metadata for the paper in the bibliography.",
            "contexts": "Text around the reference in the citing paper.",
            "intents": "The classified purposes of the reference.",
            "isInfluential": "Whether Semantic Scholar classifies the reference as influential.",
        },
    },
}
