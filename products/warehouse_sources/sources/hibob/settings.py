from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class HiBobEndpointConfig:
    name: str
    path: str
    # Key the rows live under in the response body.
    data_key: str
    # HiBob's primary employee read is a POST-for-read with a JSON body.
    method: Literal["GET", "POST"] = "GET"
    body: Optional[dict] = None
    params: Optional[dict] = None
    primary_keys: tuple[str, ...] = ("id",)
    # Where the cursor goes on the next request. None means the endpoint returns everything in one response.
    cursor_location: Optional[Literal["query", "json"]] = None
    # "employee_history": rows are nested per employee under `values` and need flattening.
    # "pointer_keys": rows are keyed by JSON pointers (e.g. `/candidate/id`) and need leaf keys.
    row_shape: Literal["flat", "employee_history", "pointer_keys"] = "flat"
    # Sent as a `since` query param set this many days before the sync starts.
    since_days_ago: Optional[int] = None


# Max page size the cursor-paginated bulk tables and hiring searches accept.
BULK_PAGE_LIMIT = 200

# Table entry ids are only documented as unique within one employee's table.
HISTORY_PRIMARY_KEYS = ("employeeId", "id")

CANDIDATE_FIELDS = (
    "/candidate/id",
    "/candidate/firstName",
    "/candidate/lastName",
    "/candidate/email",
    "/candidate/phone",
    "/candidate/title",
    "/candidate/address",
    "/candidate/photo",
    "/candidate/languages",
    "/candidate/skills",
    "/candidate/socialMedia",
    "/candidate/socialMediaLinkedIn",
    "/candidate/socialMediaFacebook",
    "/candidate/socialMediaInstagram",
    "/candidate/socialMediaThreads",
    "/candidate/socialMediaTwitter",
    "/candidate/socialMediaYouTube",
    "/candidate/socialMediaMedium",
    "/candidate/socialMediaGitHub",
    "/candidate/socialMediaReddit",
    "/candidate/socialMediaXing",
    "/candidate/socialMediaPersonalWebsite",
    "/candidate/country",
    "/candidate/city",
    "/candidate/region",
    "/candidate/education",
    "/candidate/experience",
    "/candidate/employeeId",
    "/candidate/externalUserId",
    "/candidate/importExternalId",
    "/candidate/sourceId",
    "/candidate/sourceEffectiveDate",
    "/candidate/extendConsentDueDate",
    "/candidate/extendedConsentRequestedAt",
    "/candidate/anonymizedAt",
    "/candidate/jobOpeningsToApplicationIds",
    "/candidate/dataDownloadFileId",
    "/candidate/dataDownloadRequestedAt",
    "/candidate/dataDeletionRequestedAt",
    "/candidate/dataDownloadedAt",
    "/candidate/sourceType",
    "/candidate/sourceApplicationId",
    "/candidate/sourceInstanceId",
    "/candidate/meetingBotEnabled",
    "/candidate/modificationDate",
)

APPLICATION_FIELDS = (
    "/application/id",
    "/application/status",
    "/application/candidateId",
    "/application/jobOpeningId",
    "/application/stageId",
    "/application/sourcedBy",
    "/application/sourceInstanceId",
    "/application/sourceType",
    "/application/sourceInternalId",
    "/application/sourcedByNameResolved",
    "/application/dateApplied",
    "/application/createdAt",
    "/application/lastActivityTimestamp",
    "/application/initialConsentDueDate",
    "/application/timeToHire",
    "/application/referredBy",
    "/application/evaluationScore",
    "/application/evaluationRecommendation",
    "/application/evaluationCount",
    "/application/evaluations",
    "/application/jobAdId",
    "/application/agencyId",
    "/application/agencyReferenceId",
    "/application/agencyNote",
    "/application/agencyContactFirstName",
    "/application/agencyContactLastName",
    "/application/agencyContactEmail",
    "/application/desiredSalary",
    "/application/education",
    "/application/experience",
    "/application/volunteerExperience",
    "/application/professionalAssociationsMemberships",
    "/application/qualificationsLicenses",
    "/application/initialConsentRequestedAt",
    "/application/offlineConsentMessage",
    "/application/offlineConsentGivenBy",
    "/application/dateAvailable",
    "/application/lastEmployment",
    "/application/automaticRejectionEmailMessageId",
    "/application/importResumeFileName",
    "/application/hasOffer",
    "/application/workspaceType",
    "/application/siteId",
    "/application/interviewAlert",
    "/application/referralSource",
    "/application/referralNotes",
    "/application/cvSummaryDetails",
    "/application/aiMatchingScore",
    "/application/files",
    "/application/modificationDate",
)

EMPLOYER_FIELDS = (
    "/employer/id",
    "/employer/legalName",
    "/employer/contactName",
    "/employer/employerPhoneNumber",
    "/employer/employerEmailAddress",
    "/employer/doingBusinessAs",
    "/employer/tradingAs",
    "/employer/companiesHouseRegistration",
    "/employer/supportsRemoteWorkers",
    "/employer/addressLine1",
    "/employer/addressLine2",
    "/employer/postalCode",
    "/employer/city",
    "/employer/stateProvinceRegion",
    "/employer/country",
    "/employer/fein",
    "/employer/payeReference",
    "/employer/taxIdentifier",
    "/employer/naics",
    "/employer/accountsOfficeReference",
    "/employer/organizationType",
    "/employer/taxPayerType",
    "/employer/employerStatus",
    "/employer/payrollValidationStatus",
    "/employer/validationStatusReason",
)

WORK_LOCATION_FIELDS = (
    "/workLocation/id",
    "/workLocation/employerId",
    "/workLocation/name",
    "/workLocation/type",
    "/workLocation/country",
    "/workLocation/addressLine1",
    "/workLocation/addressLine2",
    "/workLocation/postalCode",
    "/workLocation/city",
    "/workLocation/stateProvinceRegion",
    "/workLocation/status",
    "/workLocation/verificationStatus",
    "/workLocation/verificationReason",
    "/workLocation/createdAt",
    "/workLocation/createdBy",
)

SKILL_FIELDS = (
    "/skill/id",
    "/skill/name",
    "/skill/description",
    "/skill/status",
    "/skill/categoryName",
    "/skill/source",
    "/skill/externalId",
    "/skill/proficiencyLevels",
    "/skill/createdAt",
)

# The time off changes endpoint rejects a `since` older than six months; 180 days
# always falls inside that.
TIME_OFF_CHANGES_LOOKBACK_DAYS = 180

# Name of the employee time-off calendars stream. It fans out over employee ids
# (the search endpoint resolves the holiday calendar per employee), so it needs
# bespoke transport rather than the shared single-page path — routed by name in
# hibob.py.
TIME_OFF_CALENDARS = "time_off_calendars"

# Company lists come back nested (lists hold items, items can hold children), so
# they are flattened by bespoke transport — routed by name in hibob.py.
NAMED_LISTS = "named_lists"

EMPLOYERS = "employers"

# Work locations are searched per employer, so the stream fans out over employer
# ids — routed by name in hibob.py.
WORK_LOCATIONS = "work_locations"

# HiBob has no updated-at filter on employees (Airbyte is full-refresh only and
# Fivetran re-imports most tables every sync), so every stream is an honest
# full refresh. The time off changes endpoint has a `since` param but its rows
# carry no per-change timestamp to use as a watermark, so it re-reads a rolling
# window instead. Candidates and applications search accept a `modificationDate`
# filter, but neither its value format nor the result order is documented — deferred.
HIBOB_ENDPOINTS: dict[str, HiBobEndpointConfig] = {
    "employees": HiBobEndpointConfig(
        name="employees",
        path="/v1/people/search",
        data_key="employees",
        method="POST",
        # humanReadable=REPLACE flattens list/reference values into readable
        # strings; showInactive includes offboarded employees.
        body={"showInactive": True, "humanReadable": "REPLACE"},
    ),
    "tasks": HiBobEndpointConfig(
        name="tasks",
        path="/v1/tasks",
        data_key="tasks",
    ),
    TIME_OFF_CALENDARS: HiBobEndpointConfig(
        name=TIME_OFF_CALENDARS,
        path="/v1/timeoff/calendars/employees/search",
        data_key="items",
        method="POST",
        # One resolved calendar per employee, so the employee id is table-wide unique.
        primary_keys=("employeeId",),
    ),
    "employee_lifecycle": HiBobEndpointConfig(
        name="employee_lifecycle",
        path="/v1/bulk/people/lifecycle",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "employee_employment": HiBobEndpointConfig(
        name="employee_employment",
        path="/v1/bulk/people/employment",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "employee_salaries": HiBobEndpointConfig(
        name="employee_salaries",
        path="/v1/bulk/people/salaries",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "employee_deductions": HiBobEndpointConfig(
        name="employee_deductions",
        path="/v1/bulk/people/deduction",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "employee_entitlements": HiBobEndpointConfig(
        name="employee_entitlements",
        path="/v1/bulk/people/entitlement",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "employee_variable_pay": HiBobEndpointConfig(
        name="employee_variable_pay",
        path="/v1/bulk/people/variable",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "employee_dependents": HiBobEndpointConfig(
        name="employee_dependents",
        path="/v1/bulk/people/dependents",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "employee_right_to_work": HiBobEndpointConfig(
        name="employee_right_to_work",
        path="/v1/bulk/people/right-to-work",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "employee_equities": HiBobEndpointConfig(
        name="employee_equities",
        path="/v1/bulk/people/equities",
        data_key="results",
        params={"limit": BULK_PAGE_LIMIT},
        primary_keys=HISTORY_PRIMARY_KEYS,
        cursor_location="query",
        row_shape="employee_history",
    ),
    "candidates": HiBobEndpointConfig(
        name="candidates",
        path="/v1/hiring/candidates/search",
        data_key="items",
        method="POST",
        # The search returns only the fields requested, so ask for every documented candidate field.
        body={"fields": list(CANDIDATE_FIELDS), "filters": [], "limit": BULK_PAGE_LIMIT},
        cursor_location="json",
        row_shape="pointer_keys",
    ),
    "applications": HiBobEndpointConfig(
        name="applications",
        path="/v1/hiring/applications/search",
        data_key="items",
        method="POST",
        # The search returns only the fields requested, so ask for every documented application field.
        body={"fields": list(APPLICATION_FIELDS), "filters": [], "limit": BULK_PAGE_LIMIT},
        cursor_location="json",
        row_shape="pointer_keys",
    ),
    "time_off_request_changes": HiBobEndpointConfig(
        name="time_off_request_changes",
        path="/v1/timeoff/requests/changes",
        data_key="changes",
        params={"includePending": "true"},
        # An edited request gets a new requestId, so one id carries at most one change of each type.
        primary_keys=("requestId", "changeType"),
        since_days_ago=TIME_OFF_CHANGES_LOOKBACK_DAYS,
    ),
    NAMED_LISTS: HiBobEndpointConfig(
        name=NAMED_LISTS,
        path="/v1/company/named-lists",
        data_key="items",
        # Archived items stay referenced by older employee records.
        params={"includeArchived": "true"},
        # Item ids are only documented as internal ids, so scope them to their list.
        primary_keys=("listName", "id"),
    ),
    EMPLOYERS: HiBobEndpointConfig(
        name=EMPLOYERS,
        path="/v1/employers/search",
        data_key="items",
        method="POST",
        body={"fields": list(EMPLOYER_FIELDS), "filters": [], "limit": BULK_PAGE_LIMIT},
        cursor_location="json",
        row_shape="pointer_keys",
    ),
    WORK_LOCATIONS: HiBobEndpointConfig(
        name=WORK_LOCATIONS,
        path="/v1/employers/{employerId}/work-locations/search",
        data_key="items",
        method="POST",
        body={"fields": list(WORK_LOCATION_FIELDS), "filters": [], "limit": BULK_PAGE_LIMIT},
        # Work locations are read through their employer, so scope the id to it.
        primary_keys=("employerId", "id"),
        cursor_location="json",
        row_shape="pointer_keys",
    ),
    "skills": HiBobEndpointConfig(
        name="skills",
        path="/v1/skills/search",
        data_key="items",
        method="POST",
        # Without `fields` the search returns only a default subset.
        body={"fields": list(SKILL_FIELDS), "filters": [], "limit": BULK_PAGE_LIMIT},
        cursor_location="json",
        row_shape="pointer_keys",
    ),
    "skill_proficiency_levels": HiBobEndpointConfig(
        name="skill_proficiency_levels",
        path="/v1/skills/proficiency-levels",
        data_key="items",
    ),
}

ENDPOINTS = tuple(HIBOB_ENDPOINTS.keys())

# No endpoint carries a usable updated-at watermark, so every stream is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
