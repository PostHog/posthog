"""
Contract for the per-person array-collection subquery produced by
``ConversionGoalProcessor.build_array_collection_query``.

The array collection is the "upstream" stage of the conversion attribution pipeline:
for each person, it groups their conversion events and UTM pageviews into parallel
arrays. The downstream stages (ARRAY JOIN, attribution, final aggregation) consume
this shape.

This contract is defined here so that lazy computation (future PR) can materialise
a ClickHouse table with the same schema and swap it in for the live events scan,
while the attribution pipeline stays untouched.

Schema produced (in order):

* ``person_id`` — UUID of the person whose events were collected
* ``conversion_timestamps`` — Unix timestamps of conversion events (Array(Int64))
* ``conversion_math_values`` — math aggregation values parallel to the above
* ``conversion_<field>s`` — parallel array of each tracked field at conversion time
* ``utm_timestamps`` — Unix timestamps of pageviews that had a valid UTM tuple
* ``utm_<field>s`` — parallel array of each tracked field at pageview time

where ``<field>`` ranges over ``TRACKED_FIELDS`` from ``conversion_goal_processor``
(currently: campaign, source, medium, referring_domain, gclid, fbclid, gad_source).
"""

ARRAY_COLLECTION_PERSON_COLUMN = "person_id"

ARRAY_COLLECTION_CONVERSION_TIMESTAMPS_COLUMN = "conversion_timestamps"
ARRAY_COLLECTION_CONVERSION_MATH_COLUMN = "conversion_math_values"
ARRAY_COLLECTION_UTM_TIMESTAMPS_COLUMN = "utm_timestamps"
