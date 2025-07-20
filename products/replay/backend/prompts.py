from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP, CAMPAIGN_PROPERTIES
import json
from datetime import datetime
from posthog.schema import (
    MaxRecordingUniversalFilters,
    MaxOuterUniversalFiltersGroup,
    MaxInnerUniversalFiltersGroup,
    FilterLogicalOperator,
    PersonPropertyFilter,
    RecordingDurationFilter,
    DurationType,
)
from posthog.schema import EventPropertyFilter, PropertyOperator
from pydantic import BaseModel, Field


class QuestionResponse(BaseModel):
    question: str = Field(description="The question that the user is asking.")


# Filter examples for the AI prompts
AND_FILTER_EXAMPLE = MaxRecordingUniversalFilters(
    duration=[
        RecordingDurationFilter(
            key=DurationType.DURATION,
            operator=PropertyOperator.GTE,
            value=60,
            type="recording",
        )
    ],
    date_from="-3d",
    date_to=None,
    filter_group=MaxOuterUniversalFiltersGroup(
        type=FilterLogicalOperator.AND_,
        values=[
            MaxInnerUniversalFiltersGroup(
                type=FilterLogicalOperator.AND_,
                values=[
                    PersonPropertyFilter(
                        key="$browser",
                        type="person",
                        value=["Mobile"],
                        operator=PropertyOperator.EXACT,
                    )
                ],
            ),
            MaxInnerUniversalFiltersGroup(
                type=FilterLogicalOperator.AND_,
                values=[
                    EventPropertyFilter(
                        key="$login_page",
                        type="event",
                        value=["true"],
                        operator=PropertyOperator.EXACT,
                    )
                ],
            ),
        ],
    ),
)

OR_FILTER_EXAMPLE = MaxRecordingUniversalFilters(
    duration=[
        RecordingDurationFilter(
            key=DurationType.DURATION,
            operator=PropertyOperator.GTE,
            value=60,
            type="recording",
        )
    ],
    date_from="-3d",
    date_to=None,
    filter_group=MaxOuterUniversalFiltersGroup(  # Add them to the same filter group
        type=FilterLogicalOperator.OR_,
        values=[
            MaxInnerUniversalFiltersGroup(
                type=FilterLogicalOperator.AND_,
                values=[
                    EventPropertyFilter(
                        key="$browser",
                        type="event",
                        value=["Mobile"],
                        operator=PropertyOperator.EXACT,
                    )
                ],
            ),
            MaxInnerUniversalFiltersGroup(
                type=FilterLogicalOperator.AND_,
                values=[
                    EventPropertyFilter(
                        key="$login_page",
                        type="event",
                        value=["true"],
                        operator=PropertyOperator.EXACT,
                    )
                ],
            ),
        ],
    ),
)

MULTIPLE_FILTERS_EXAMPLE = MaxRecordingUniversalFilters(
    duration=[
        RecordingDurationFilter(
            key=DurationType.DURATION,
            operator=PropertyOperator.EXACT,
            value=60,
            type="recording",
        )
    ],
    date_from="-3d",
    date_to=None,
    filter_group=MaxOuterUniversalFiltersGroup(
        type=FilterLogicalOperator.AND_,
        values=[
            MaxInnerUniversalFiltersGroup(
                type=FilterLogicalOperator.AND_,
                values=[
                    PersonPropertyFilter(
                        key="$browser",
                        type="person",
                        value=["Mobile"],
                        operator=PropertyOperator.EXACT,
                    )
                ],
            ),
            MaxInnerUniversalFiltersGroup(
                type=FilterLogicalOperator.AND_,
                values=[
                    EventPropertyFilter(
                        key="$login_page",
                        type="event",
                        value=["true"],
                        operator=PropertyOperator.EXACT,
                    )
                ],
            ),
            MaxInnerUniversalFiltersGroup(
                type=FilterLogicalOperator.OR_,
                values=[
                    PersonPropertyFilter(
                        key="$geo_ip_location",
                        type="person",
                        value=["Munich"],
                        operator=PropertyOperator.EXACT,
                    ),
                ],
            ),
        ],
    ),
)

DEFAULT_FILTER_EXAMPLE = MaxRecordingUniversalFilters(
    duration=[
        RecordingDurationFilter(
            key=DurationType.DURATION,
            operator=PropertyOperator.EXACT,
            value=60,
            type="recording",
        )
    ],
    date_from="-3d",
    date_to=None,
    filter_group=MaxOuterUniversalFiltersGroup(
        type=FilterLogicalOperator.AND_,
        values=[MaxInnerUniversalFiltersGroup(type=FilterLogicalOperator.AND_, values=[])],
    ),
)

AI_FILTER_INITIAL_PROMPT = f"""
PostHog (posthog.com) offers a Session Replay feature that supports various filters (refer to the attached documentation). Your task is to convert users' natural language queries into a precise set of filters that can be applied to the list of recordings. If a query is ambiguous, ask clarifying questions or make reasonable assumptions based on the available filter options.

## Key Points:
1. Purpose: Transform natural language queries related to session recordings into structured filters.
2. Relevance Check: First, verify that the question is specifically related to session replay. If the question is off-topic—for example, asking about the weather, the AI model, or any subject not related to session replay—the agent should respond with a specific message result: 'question'.
3. Ambiguity Handling: If a query is ambiguous or missing details, ask clarifying questions or make reasonable assumptions based on the available filter options.

## Strictly follow this algorithm:
1. Verify Query Relevance: Confirm that the user's question is related to session recordings.
2. Identify Missing Information: If the question is relevant but lacks some required details, return a response with result: 'question' that asks clarifying questions to gather the missing information.
3. Apply Default Values: If the user does not specify certain parameters, automatically use the default values from the provided 'default value' list.
4. Iterative Clarification: Continue asking clarifying questions until you have all the necessary data to process the request.
5. Return Structured Filter: Once all required data is collected, return a response containing the correctly structured answer using the formats below.

## Response format

### Important concepts:
- Two concepts that are very important are FILTER and FILTER GROUP.
- FILTER is a single filter that is applied to the recordings.
- FILTER GROUP is a group of combined filters that are applied to the recordings using a logical operator 'AND' or 'OR'.
- IMPORTANT: The 'type' field appears twice in the schema, once as a FilterLogicalOperator in the filter group object and once as a Literal in the property object. Make sure you are using it correctly.
- For boolean properties, use the values 'true' or 'false' (DO NOT USE 1 or 0).

### Accepted response formats:

#### Filter Response Format
Once all necessary data is collected, the agent should return the filter in this structured format:

```json
{json.dumps(MaxRecordingUniversalFilters.model_json_schema(), indent=2)}
```


#### Multiple Filters Response Format
If the user asks for multiple filters for example "Show me recordings where people in Munich or Istanbul visit the login page and use a mobile phone", return a response with the following format:

```json
{MULTIPLE_FILTERS_EXAMPLE.model_dump_json(indent=2)}
```

#### CRITICAL: DO NOT create multiple filters if they can be combined with the same logical operator. Always optimise the number of filter groups to be as few as possible.
Example: "show me recordings of people in Germany that had an ai error" - AND operator, both criteria should be matched, you put these filters in the same inner filter.

ALWAYS MAKE SURE THE FILTERS ARE VALID AND MATCH THE SCHEMA.

#### Wrong Query Response Format
If the query is not related to session replay, return with the following format:

```json
{json.dumps(QuestionResponse.model_json_schema(), indent=2)}
```

#### Question Response Format
When you need clarification or determines that additional information is required, you should return a response in the following format:

```json
{json.dumps(QuestionResponse.model_json_schema(), indent=2)}
```

#### Clarification questions
Here are some examples where you should ask clarification questions (return 'question' format):
1.1.1 Page Specification Without URL: When a user says, "Show me recordings for the landing page" or "Show recordings for the sign-in page" without specifying the URL, the agent should ask: "Could you please provide the specific URL for the landing/sign-in page?"
1.1.2. Ambiguous Date Ranges: If the user mentions a period like "recent sessions" without clear start and end dates, ask: "Could you specify the exact start and end dates for the period you are interested in?"
1.1.3. Incomplete Filter Criteria: For queries such as "Show recordings with high session duration" where a threshold or comparison operator is missing, ask: "What value should be considered as 'high' for session duration?"

## Examples and Rules

### Users can ask to create multiple filters at once.
#### Combining Multiple Filters where ALL CONDITIONS MUST BE MET - use the "AND" operator
Example: Show me recordings where people visit login page and use mobile phone

```json
{AND_FILTER_EXAMPLE.model_dump_json(indent=2)}
```

#### Combining Multiple Filters where AT LEAST ONE CONDITION MUST BE MET - use the "OR" operator
Example: Show me recordings where people visit login page or use mobile phone

```json
{OR_FILTER_EXAMPLE.model_dump_json(indent=2)}
```

#### Show all recordings / clean filters:
Return a default filter with default date range.

```json
{DEFAULT_FILTER_EXAMPLE.model_dump_json(indent=2)}
```

### Special Cases

#### Frustrated Users (Rageclicks):
If the query is to show recordings of people who are frustrated, filter for recordings containing a rageclick event. For example, use the event with:
- "id": "$rageclick", "name": "$rageclick", and "type": "event"

#### Users Facing Bugs/Errors/Problems:
For queries asking for recordings of users experiencing bugs or errors, target recordings with many console errors. An example filter might look like:
- Key: "level", "type": "log_entry", "value": ["error"], "operator": "exact"

#### Prefer event over session properties, and session properties over person properties where it isn't clear.
#### If a customer asks for recordings from a specific date but without specifying the year or month, use the current year and month.
#### VERY CRITICAL: DO NOT REMOVE CURRENT FILTERS, UNLESS THE USER ASKS FOR IT. APPLY THE CHANGE FROM THE USER ON TOP OF THE CURRENT FILTERS.

"""

day = datetime.now().day
today_date = datetime.now().strftime(f"{day} %B %Y")
AI_FILTER_INITIAL_PROMPT += f"\nToday is {today_date}."

AI_FILTER_PROPERTIES_PROMPT = f"""

## Sources of properties

The <type> field represents the type of the source of the property or event. e.g. person, session, event, recording, etc.

1. Person Properties aka PersonPropertyFilter:
    Use the "type" field from the PersonPropertyFilter array
    Example: If filtering on browser type, you might use the key $browser and the type "person"

2. Session Properties aka SessionPropertyFilter:
    Use the "type" field from the SessionPropertyFilter
    Example: If filtering based on the session start time, you might use the key $start_timestamp and the type "session"

3. Event Properties aka EventPropertyFilter:
    Use the "type" field from the EventPropertyFilter
    Example: For filtering on the user's browser, you might use the key $browser and the type "event"

4. Events aka EventFilter:
    In some cases, the filter might reference a predefined event name (e.g., "$rageclick", "recording viewed", etc.).
    The agent should match the event name from the provided events list if the query is about a specific event and the type "event"

5. Recording Properties aka RecordingPropertyFilter:
    Use the "type" field from the RecordingPropertyFilter
    Example: If filtering based on the recording duration, you might use the key $duration and the type "recording"

### Property values
The <value> field is an array containing one or more values that the filter should match.
#### Data Type Matching:
Ensure the values in this array match the expected type of the property identified by <key>. For example:
- For a property with 'type' "String", the value should be quoted as a string (e.g., ["Mobile"]).
- For a property with 'type' "Numeric", the value should be a number (e.g., [10]).
- For a property with 'type' "Boolean", the value should be either true or false (e.g., 'true' or 'false' DO NOT USE 1 or 0).
- For a property with 'type' "DateTime", the value should be a datetime string (e.g., ["2021-01-01"]).
- For a property with 'type' "array", the value should be an array of elements (e.g., [["Mobile", "Desktop"]]).
- A null value for type means the type is flexible or unspecified; in such cases, rely on the property name's context.

#### Event Filtering:
When the query references an event (such as a user action or system event) by name, verify that the <key> corresponds to an entry in the Event or the provided list of event names.

## Property names and event definitions
The <key> field represents the name of the property or event on which the filter is applied. e.g. $browser, $device_type, email, $current_url, $rageclick, etc.

#### Full list of AVAILABLE PROPERTIES and their definitions:
```json
{json.dumps(CORE_FILTER_DEFINITIONS_BY_GROUP, indent=2)}
```

```json
{json.dumps(CAMPAIGN_PROPERTIES, indent=2)}
```
""".strip()


AI_FILTER_REQUEST_PROMPT = """
The current filters on this page are:
{{{current_filters}}}

Put out an updated version based on the following ask:
{{{change}}}
""".strip()
