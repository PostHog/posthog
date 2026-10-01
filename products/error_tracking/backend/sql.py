#
# error_tracking_issue_fingerprint_overrides: This table contains rows for all (team_id, fingerprint)
# pairs where the $exception_issue_id has changed.
#


def TRUNCATE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE}"


INSERT_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES = """
INSERT INTO error_tracking_issue_fingerprint_overrides (fingerprint, issue_id, team_id, is_deleted, version, _timestamp, _offset, _partition) SELECT %(fingerprint)s, %(issue_id)s, %(team_id)s, %(is_deleted)s, %(version)s, now(), 0, 0 VALUES
"""

# WarpStream-shared Kafka engine table + MV for error_tracking_issue_fingerprint_overrides.
# Coexists with the MSK-pointed table during cut-over; the MSK side gets dropped in a follow-up
# migration once produce traffic has fully shifted to warpstream-shared.


#
# error_tracking_fingerprint_issue_state: Contains issue metadata alongside fingerprint
# mappings, eliminating the need for Postgres JOINs in the list query.
#

ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE = "error_tracking_fingerprint_issue_state"
ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE = f"raw_{ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE}"


INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE = """
INSERT INTO error_tracking_fingerprint_issue_state (fingerprint, issue_id, team_id, issue_name, issue_description, issue_status, issue_severity, assigned_user_id, assigned_role_id, first_seen, is_deleted, version, _timestamp, _offset, _partition) SELECT %(fingerprint)s, %(issue_id)s, %(team_id)s, %(issue_name)s, %(issue_description)s, %(issue_status)s, %(issue_severity)s, %(assigned_user_id)s, %(assigned_role_id)s, %(first_seen)s, %(is_deleted)s, %(version)s, now(), 0, 0 VALUES
"""

# WarpStream-shared Kafka engine table + MV for error_tracking_fingerprint_issue_state.
# Coexists with the MSK-pointed table during cut-over.


# IMPORTANT: The following table definitions are obsolete and were replaced by the general-purpose
# document_embeddings tables in migration 0155. However, they MUST remain here for historical
# migration compatibility - migration 0153 references these functions to create the tables,
# and migration 0155 drops them. Removing these definitions would break the migration chain.
# DO NOT remove these definitions or the functions below.
