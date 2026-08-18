from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_BASE = "https://api.semanticscholar.org/api-docs/graph"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Papers": {
        "description": "Papers matching the configured search query, from the Semantic Scholar Academic Graph.",
        "docs_url": _DOCS_BASE,
        "columns": {
            "paperId": "Semantic Scholar's primary unique identifier for the paper.",
            "corpusId": "Semantic Scholar's secondary unique identifier for the paper. Used by the Datasets API.",
            "externalIds": "Object of the paper's identifiers in external sources, such as DOI, ArXiv and PubMed.",
            "url": "URL of the paper on the Semantic Scholar website.",
            "title": "Title of the paper.",
            "abstract": "The paper's abstract, when available.",
            "venue": "Name of the paper's publication venue.",
            "journal": "Journal or conference the paper was published in, including volume, pages and name.",
            "year": "Year the paper was published.",
            "publicationDate": "Date the paper was published, as YYYY-MM-DD. Null when only a year is known.",
            "publicationTypes": "The paper's publication types, for example JournalArticle or Conference.",
            "referenceCount": "Total number of papers this paper references.",
            "citationCount": "Total number of papers that cite this paper.",
            "influentialCitationCount": "Subset of citationCount where the citing paper is highly influential.",
            "isOpenAccess": "Whether a free copy of the paper is publicly available.",
            "openAccessPdf": "Link to a free PDF of the paper, when isOpenAccess is true.",
            "fieldsOfStudy": "High-level academic fields the paper belongs to, sourced from external providers.",
            "s2FieldsOfStudy": "High-level academic fields Semantic Scholar itself assigned to the paper.",
            "authors": "List of the paper's authors, each with their authorId and name.",
            "tldr": "Semantic Scholar's one-sentence, AI-generated summary of the paper.",
        },
    },
    "Authors": {
        "description": "Authors matching the configured author search query, from the Semantic Scholar Academic Graph.",
        "docs_url": _DOCS_BASE,
        "columns": {
            "authorId": "Semantic Scholar's unique identifier for the author.",
            "externalIds": "Object of the author's ORCID and DBLP identifiers, when known.",
            "url": "URL of the author's profile on the Semantic Scholar website.",
            "name": "Author's name.",
            "affiliations": "Organizational affiliations listed for the author.",
            "homepage": "The author's homepage, when known.",
            "paperCount": "Total number of papers attributed to the author.",
            "citationCount": "Total number of citations across all of the author's papers.",
            "hIndex": "Author's h-index, a measure of citation impact.",
        },
    },
}
