"""Uploaded people lists: each row creates or updates a person, and the people form a static cohort."""

from products.workflows.backend.services.people_import import (
    MAX_PEOPLE_IMPORT_ROWS,
    PeopleImportInvalid,
    start_people_import,
)

__all__ = ["MAX_PEOPLE_IMPORT_ROWS", "PeopleImportInvalid", "start_people_import"]
