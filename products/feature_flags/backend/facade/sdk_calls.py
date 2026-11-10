"""PostHog SDK calls that read a feature flag.

Agents that search a repository for a flag's checks get this list in their prompt, besides the flag key:
the flag code analysis and the experiment flag cleanup.
"""

# One list across the JavaScript, React, Python, Go, and other SDKs, so each prompt searches for the same calls.
FLAG_SDK_CALLS = (
    "isFeatureEnabled, getFeatureFlag, getFeatureFlagPayload, getFeatureFlagResult, onFeatureFlags, "
    "useFeatureFlag, useFeatureFlagEnabled, useFeatureFlagVariantKey, useFeatureFlagPayload, useFeatureFlagResult, "
    "useActiveFeatureFlags, PostHogFeature, evaluateFlags, getFlag, isEnabled, feature_enabled, get_feature_flag, "
    "get_feature_flag_payload, evaluate_flags, get_flag, is_enabled, GetFeatureFlag, IsFeatureEnabled"
)
