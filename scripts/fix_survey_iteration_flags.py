"""
Script to fix survey internal_targeting_flag filters for surveys with iterations.

Bug: When iterations were added to an existing survey, the internal_targeting_flag
was not updated to include the iteration suffix in the property keys.

Example of broken state:
  - Property key: $survey_responded/019a1782-40cf-0000-6367-1ec81283534a

Expected state (with iteration):
  - Property key: $survey_responded/019a1782-40cf-0000-6367-1ec81283534a/1

Usage:
    # In Django shell on production pod:
    exec(open('scripts/fix_survey_iteration_flags.py').read())

    # Or import and run:
    from scripts.fix_survey_iteration_flags import fix_affected_surveys
    fix_affected_surveys(dry_run=True)  # Preview changes
    fix_affected_surveys(dry_run=False)  # Apply changes
"""

from posthog.models import Survey
from posthog.models.surveys.util import SurveyEventProperties

# Set to False to actually apply fixes
DRY_RUN = True


def find_affected_surveys(specific_survey_id=None):
    """
    Find surveys that have iterations configured but their internal_targeting_flag
    has properties WITHOUT the iteration suffix.
    """
    affected_surveys = []

    queryset = Survey.objects.filter(
        iteration_count__isnull=False,
        iteration_count__gt=0,
        internal_targeting_flag__isnull=False,
    ).select_related("internal_targeting_flag")

    if specific_survey_id:
        queryset = queryset.filter(id=specific_survey_id)

    for survey in queryset:
        flag = survey.internal_targeting_flag
        if not flag or not flag.filters:
            continue

        groups = flag.filters.get("groups", [])
        if not groups:
            continue

        properties = groups[0].get("properties", [])
        survey_id_str = str(survey.id)

        # Check if any property is missing the iteration suffix
        for prop in properties:
            key = prop.get("key", "")

            # Check for $survey_dismissed/{survey_id} or $survey_responded/{survey_id}
            # without the /{iteration} suffix
            if (
                key == f"{SurveyEventProperties.SURVEY_DISMISSED}/{survey_id_str}"
                or key == f"{SurveyEventProperties.SURVEY_RESPONDED}/{survey_id_str}"
            ):
                affected_surveys.append(
                    {
                        "survey": survey,
                        "flag": flag,
                        "current_filters": flag.filters,
                        "problematic_key": key,
                    }
                )
                break

    return affected_surveys


def build_correct_filters(survey):
    """Build the correct filters with iteration suffix."""
    current_iteration = survey.current_iteration or 1
    survey_key = f"{survey.id}/{current_iteration}"

    return {
        "groups": [
            {
                "variant": "",
                "rollout_percentage": 100,
                "properties": [
                    {
                        "key": f"{SurveyEventProperties.SURVEY_DISMISSED}/{survey_key}",
                        "value": "is_not_set",
                        "operator": "is_not_set",
                        "type": "person",
                    },
                    {
                        "key": f"{SurveyEventProperties.SURVEY_RESPONDED}/{survey_key}",
                        "value": "is_not_set",
                        "operator": "is_not_set",
                        "type": "person",
                    },
                ],
            }
        ]
    }


def fix_affected_surveys(dry_run=True, specific_survey_id=None):
    """
    Find and fix surveys with broken iteration flags.

    Args:
        dry_run: If True, only log what would be changed without saving.
        specific_survey_id: If provided, only check/fix this specific survey.
    """
    print("=" * 80)
    print(f"Survey Iteration Flag Fix Script")
    print(f"DRY_RUN: {dry_run}")
    if specific_survey_id:
        print(f"Targeting specific survey: {specific_survey_id}")
    print("=" * 80)
    print()

    affected = find_affected_surveys(specific_survey_id)

    if not affected:
        print("No affected surveys found.")
        return

    print(f"Found {len(affected)} affected survey(s):\n")

    for item in affected:
        survey = item["survey"]
        flag = item["flag"]

        print("-" * 60)
        print(f"Survey ID:        {survey.id}")
        print(f"Survey Name:      {survey.name}")
        print(f"Team ID:          {survey.team_id}")
        print(f"Iteration Count:  {survey.iteration_count}")
        print(f"Current Iter:     {survey.current_iteration}")
        print(f"Flag ID:          {flag.id}")
        print(f"Flag Key:         {flag.key}")
        print()

        # Show current problematic state
        print("CURRENT (broken) filter properties:")
        current_groups = flag.filters.get("groups", [])
        if current_groups:
            for prop in current_groups[0].get("properties", []):
                print(f"  - {prop.get('key')}")
        print()

        # Show what it should be
        correct_filters = build_correct_filters(survey)
        print("EXPECTED (fixed) filter properties:")
        for prop in correct_filters["groups"][0]["properties"]:
            print(f"  - {prop.get('key')}")
        print()

        if not dry_run:
            # Apply the fix - preserve other keys, override groups
            flag.filters = {**flag.filters, **correct_filters}
            flag.save()
            print(">>> FIXED: Flag filters updated and saved.")
        else:
            print(">>> DRY RUN: No changes made.")

        print()

    print("=" * 80)
    if dry_run:
        print(f"DRY RUN complete. {len(affected)} survey(s) would be fixed.")
        print("Run with dry_run=False to apply changes.")
    else:
        print(f"DONE. Fixed {len(affected)} survey(s).")
    print("=" * 80)


# Auto-run when executed
if __name__ == "__main__" or True:  # True ensures it runs in exec()
    # You can test with a specific survey first:
    # fix_affected_surveys(dry_run=True, specific_survey_id="019a1782-40cf-0000-6367-1ec81283534a")

    # Or run for all affected surveys:
    fix_affected_surveys(dry_run=DRY_RUN)


# =============================================================================
# COMPACT VERSION FOR INTERACTIVE DJANGO SHELL (no blank lines in loops)
# =============================================================================
# Copy everything between the triple quotes and paste into Django shell:
COPY_PASTE_FIX_SCRIPT_COMPACT = """
from posthog.models import Survey
DRY_RUN = True
affected = []
for survey in Survey.objects.filter(iteration_count__isnull=False, iteration_count__gt=0, internal_targeting_flag__isnull=False).select_related("internal_targeting_flag"):
    flag = survey.internal_targeting_flag
    if not flag or not flag.filters:
        continue
    groups = flag.filters.get("groups", [])
    if not groups:
        continue
    sid = str(survey.id)
    current_iter = survey.current_iteration or 1
    expected_suffix = f"{sid}/{current_iter}"
    is_affected = False
    reason = ""
    for prop in groups[0].get("properties", []):
        key = prop.get("key", "")
        if key == f"$survey_dismissed/{sid}" or key == f"$survey_responded/{sid}":
            is_affected = True
            reason = "missing iteration suffix"
            break
        if key.startswith(f"$survey_dismissed/{sid}/") or key.startswith(f"$survey_responded/{sid}/"):
            if expected_suffix not in key:
                is_affected = True
                reason = "wrong iteration number"
                break
    if is_affected:
        affected.append((survey, flag, reason))

print(f"Found {len(affected)} affected survey(s)")
for survey, flag, reason in affected:
    print(f"Survey: {survey.id} | Team: {survey.team_id} | Iter: {survey.current_iteration} | Reason: {reason}")
    print(f"  Current: {[p['key'] for p in flag.filters.get('groups', [{}])[0].get('properties', [])]}")
    iteration = survey.current_iteration or 1
    new_filters = {"groups": [{"variant": "", "rollout_percentage": 100, "properties": [{"key": f"$survey_dismissed/{survey.id}/{iteration}", "value": "is_not_set", "operator": "is_not_set", "type": "person"}, {"key": f"$survey_responded/{survey.id}/{iteration}", "value": "is_not_set", "operator": "is_not_set", "type": "person"}]}]}
    print(f"  Fixed:   {[p['key'] for p in new_filters['groups'][0]['properties']]}")
    if not DRY_RUN:
        flag.filters = {**flag.filters, **new_filters}
        flag.save()
        print("  >>> SAVED")
    else:
        print("  >>> DRY RUN")

print(f"{'DRY RUN complete' if DRY_RUN else 'DONE'}. {len(affected)} survey(s).")
"""


# =============================================================================
# FULL VERSION (for running via exec() or file)
# =============================================================================
# Copy everything between the triple quotes and paste into Django shell:
COPY_PASTE_FIX_SCRIPT = """
from posthog.models import Survey

DRY_RUN = True  # Set to False to apply fixes

affected = []
for survey in Survey.objects.filter(
    iteration_count__isnull=False,
    iteration_count__gt=0,
    internal_targeting_flag__isnull=False,
).select_related("internal_targeting_flag"):
    flag = survey.internal_targeting_flag
    if not flag or not flag.filters:
        continue
    groups = flag.filters.get("groups", [])
    if not groups:
        continue

    sid = str(survey.id)
    current_iter = survey.current_iteration or 1
    expected_suffix = f"{sid}/{current_iter}"

    is_affected = False
    reason = ""
    for prop in groups[0].get("properties", []):
        key = prop.get("key", "")
        if key == f"$survey_dismissed/{sid}" or key == f"$survey_responded/{sid}":
            is_affected = True
            reason = "missing iteration suffix"
            break
        if key.startswith(f"$survey_dismissed/{sid}/") or key.startswith(f"$survey_responded/{sid}/"):
            if expected_suffix not in key:
                is_affected = True
                reason = "wrong iteration number"
                break

    if is_affected:
        affected.append((survey, flag, reason))

print(f"\\nFound {len(affected)} affected survey(s)\\n")

for survey, flag, reason in affected:
    print(f"Survey: {survey.id} | Team: {survey.team_id} | Iter: {survey.current_iteration} | Reason: {reason}")
    print(f"  Current: {[p['key'] for p in flag.filters.get('groups', [{}])[0].get('properties', [])]}")

    iteration = survey.current_iteration or 1
    new_filters = {
        "groups": [{
            "variant": "",
            "rollout_percentage": 100,
            "properties": [
                {"key": f"$survey_dismissed/{survey.id}/{iteration}", "value": "is_not_set", "operator": "is_not_set", "type": "person"},
                {"key": f"$survey_responded/{survey.id}/{iteration}", "value": "is_not_set", "operator": "is_not_set", "type": "person"},
            ],
        }]
    }
    print(f"  Fixed:   {[p['key'] for p in new_filters['groups'][0]['properties']]}")

    if not DRY_RUN:
        flag.filters = {**flag.filters, **new_filters}
        flag.save()
        print("  >>> SAVED")
    else:
        print("  >>> DRY RUN")
    print()

print(f"{'DRY RUN complete' if DRY_RUN else 'DONE'}. {len(affected)} survey(s) {'would be' if DRY_RUN else ''} fixed.")
"""


# =============================================================================
# DEBUG SCRIPT - INVESTIGATE A SPECIFIC SURVEY
# =============================================================================
# Copy everything between the triple quotes and paste into Django shell:
COPY_PASTE_DEBUG_SCRIPT = """
# Change this to investigate any survey
SURVEY_ID = "019928ce-f490-0000-377c-3b4c5ec41eab"

from posthog.models import Survey
from posthog.models.activity_logging.activity_log import ActivityLog

survey = Survey.objects.select_related("internal_targeting_flag").get(id=SURVEY_ID)

print(f"Survey: {survey.name}")
print(f"Team: {survey.team_id}")
print(f"current_iteration: {survey.current_iteration}")
print(f"iteration_count: {survey.iteration_count}")
print(f"iteration_frequency_days: {survey.iteration_frequency_days}")
print(f"iteration_start_dates: {survey.iteration_start_dates}")
print(f"start_date: {survey.start_date}")
print(f"end_date: {survey.end_date}")

if survey.internal_targeting_flag:
    flag = survey.internal_targeting_flag
    print(f"\\nFlag ID: {flag.id}")
    print(f"Flag key: {flag.key}")
    props = flag.filters.get("groups", [{}])[0].get("properties", [])
    print(f"Flag properties: {[p['key'] for p in props]}")

print("\\nRecent activity:")
for a in ActivityLog.objects.filter(team_id=survey.team_id, scope="Survey", item_id=str(survey.id)).order_by("-created_at")[:10]:
    print(f"  {a.created_at} | {a.activity} | {a.detail}")
"""
