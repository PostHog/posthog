"""Stamphog release version.

Stamped onto the review-completed analytics event, the LLM trace properties,
and the verdict comment's mechanics table, so verdict quality and reviewer
behavior can be segmented by version in LLM analytics. Bump it in the same PR
as any behavior-affecting change to the engine, the prompt scaffold, or the
review guidance (semver, pre-releases like 2.0.0b1 welcome). Policy data
changes don't need a bump - they are tracked by the policy sha shown next to
the version in the verdict table.
"""

STAMPHOG_VERSION = "2.0.0b2"
