from posthog.ph_client import feature_enabled_or_false


def organization_flag_enabled(flag_key: str, organization_id: str) -> bool:
    # Evaluated locally: callers sit on request and start paths, and a miss would otherwise block them on a call
    # to /flags. The flag has to target the organization id sent here, or it reads false for everyone.
    return feature_enabled_or_false(
        flag_key,
        organization_id,
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
