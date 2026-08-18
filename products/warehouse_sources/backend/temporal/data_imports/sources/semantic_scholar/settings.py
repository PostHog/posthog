from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org/graph/v1"

PAPERS_ENDPOINT = "Papers"
AUTHORS_ENDPOINT = "Authors"

ENDPOINTS = (PAPERS_ENDPOINT, AUTHORS_ENDPOINT)

# `publicationDate` is fixed once a paper is indexed, unlike `citationCount` and friends, which
# the API keeps recomputing as new papers cite it — safe to checkpoint an incremental sync on.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    PAPERS_ENDPOINT: [incremental_field("publicationDate", IncrementalFieldType.Date)],
}

# `paperId` is always returned by the API in addition to this list.
PAPER_FIELDS = (
    "corpusId,externalIds,url,title,abstract,venue,year,referenceCount,citationCount,"
    "influentialCitationCount,isOpenAccess,openAccessPdf,fieldsOfStudy,s2FieldsOfStudy,"
    "publicationTypes,publicationDate,journal,authors,tldr"
)

# `authorId` is always returned by the API in addition to this list.
AUTHOR_FIELDS = "externalIds,url,name,affiliations,homepage,paperCount,citationCount,hIndex"

# Vendor maximum for /author/search's `limit` param (default is 100).
AUTHOR_SEARCH_PAGE_SIZE = 1000
