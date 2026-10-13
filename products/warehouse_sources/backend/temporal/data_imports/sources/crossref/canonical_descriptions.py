"""Canonical, documentation-sourced descriptions for Crossref endpoints and columns.

Sourced from the official Crossref REST API documentation
(https://github.com/CrossRef/rest-api-doc). Keyed by the resource names in `settings.py`
`ENDPOINTS`. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Works": {
        "description": "Scholarly work metadata registered with Crossref: journal articles, books, datasets, and other content assigned a DOI.",
        "docs_url": "https://github.com/CrossRef/rest-api-doc#work",
        "columns": {
            "DOI": "The Digital Object Identifier of the work.",
            "title": "The title(s) of the work.",
            "publisher": "Name of the work's publisher.",
            "type": "The type of the work (e.g. journal-article, book-chapter).",
            "member": "The Crossref member ID of the depositing publisher.",
            "prefix": "The DOI prefix associated with the work's registrant.",
            "container-title": "Name of the work's parent container (e.g. the journal name).",
            "issued": "Date on which the work was issued.",
            "URL": "The URL form of the work's DOI.",
            "is-referenced-by-count": "Number of other works that cite this work, as counted by Crossref.",
            "references-count": "Number of references this work cites.",
            "language": "The language of the work.",
            "ISSN": "The ISSN(s) of the work's container (e.g. journal).",
            "author": "The list of authors of the work.",
            "license": "License(s) under which the work is made available.",
            "indexed_date": "When Crossref's search index was last updated for this work.",
            "deposited_date": "When the work's metadata was last deposited with Crossref.",
            "created_date": "When the work's metadata record was first registered with Crossref.",
        },
    },
    "Members": {
        "description": "Publisher and society organizations that deposit metadata with Crossref.",
        "docs_url": "https://github.com/CrossRef/rest-api-doc#members",
        "columns": {
            "id": "The Crossref member ID.",
            "primary-name": "The organization's primary name.",
            "location": "The organization's location.",
            "prefixes": "DOI prefixes registered to this member.",
            "counts": "Counts of DOIs registered by this member.",
        },
    },
    "Funders": {
        "description": "Funding bodies in Crossref's Open Funder Registry, used to tag works with grant and funding information.",
        "docs_url": "https://github.com/CrossRef/rest-api-doc#funders",
        "columns": {
            "id": "The Funder ID, a Crossref-issued identifier from the Open Funder Registry.",
            "name": "The funder's name.",
            "alt-names": "Alternate names for the funder.",
            "uri": "The funder's DOI URI.",
            "location": "The funder's location.",
            "replaces": "Funder IDs this funder replaces.",
            "replaced-by": "Funder IDs that replace this funder.",
        },
    },
    "Types": {
        "description": "The controlled vocabulary of work types Crossref recognizes (journal-article, book-chapter, dataset, etc).",
        "docs_url": "https://github.com/CrossRef/rest-api-doc#types",
        "columns": {
            "id": "The type's identifier, used in a work's `type` field.",
            "label": "The type's human-readable label.",
        },
    },
    "Licenses": {
        "description": "Distinct license URLs referenced by works, with a count of works that use each.",
        "docs_url": "https://github.com/CrossRef/rest-api-doc#licenses",
        "columns": {
            "URL": "The license URL.",
            "work-count": "Number of works referencing this license.",
        },
    },
}
