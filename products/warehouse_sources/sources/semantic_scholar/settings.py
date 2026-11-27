API_ROOT = "https://api.semanticscholar.org/graph"
API_DOCS_URL = "https://api.semanticscholar.org/api-docs/graph"
MAX_PAPERS = 10_000_000
ENDPOINTS = ("papers", "citations", "references", "paper_authors")
PAPER_FIELDS = (
    "paperId,corpusId,externalIds,url,title,abstract,venue,year,publicationDate,"
    "referenceCount,citationCount,influentialCitationCount,isOpenAccess,openAccessPdf,"
    "fieldsOfStudy,s2FieldsOfStudy,publicationTypes,journal,authors"
)
EDGE_FIELDS = "paperId,title,year,publicationDate,authors,contexts,intents,isInfluential"
AUTHOR_FIELDS = "authorId,externalIds,url,name,affiliations,homepage,paperCount,citationCount,hIndex"
RELATED_PAPER_FIELDS = {"citations": "citingPaper", "references": "citedPaper"}
CHILD_PATHS = {"citations": "citations", "references": "references", "paper_authors": "authors"}
CHILD_FIELDS = {"citations": EDGE_FIELDS, "references": EDGE_FIELDS, "paper_authors": AUTHOR_FIELDS}
PRIMARY_KEYS = {
    "papers": ["paperId"],
    "citations": ["paper_id", "related_paper_id"],
    "references": ["paper_id", "related_paper_id"],
    "paper_authors": ["paper_id", "authorId"],
}
AUTH_ERROR = "Semantic Scholar rejected the API key. Check your key and its API access."
QUERY_ERROR = "Semantic Scholar rejected the search query. Check the query syntax."
LIMIT_ERROR = "The search exceeds the Semantic Scholar bulk limit. Use a more specific search query."
