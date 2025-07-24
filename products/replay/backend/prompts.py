import json
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP, CAMPAIGN_PROPERTIES

# SESSION_REPLAY_RESPONSE_FORMATS_PROMPT = """
# <response_formats>
# Notes:
# 1. Replace <date_from> and <date_to> with valid date strings.
# 2. The filter_group structure is nested. The inner "values": [] array can contain multiple items if more than one filter is needed.
# 3. Ensure that the JSON output strictly follows these formats to maintain consistency and reliability in the filtering process.
# 4. WHEN GENERATING A FILTER BASED ON MORE THAN ONE PROPERTY ALWAYS MAKE SURE TO KEEP THE OLD FILTERS. NEVER REMOVE ANY FILTERS.
# </response_formats>

# """.strip()


SESSION_REPLAY_EXAMPLES_PROMPT = """
<examples_and_rules>
## Examples and Rules

1. Combining Filters with the AND Operator

If you need to combine multiple filter conditions using the AND operator, structure them as follows:

json
{
"data": {
    "date_from": "<date_from>",
    "date_to": "<date_to>",
    "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": PropertyOperator.GreaterThan}], // Always include the duration filter.
    "filter_group": {
    "type": FilterLogicalOperator.AND,
    "values": [
        {
        "type": FilterLogicalOperator.AND,
        "values": [
            {
            "key": "<key>",
            "type": PropertyFilterType.<Type>,  // e.g., PropertyFilterType.Person
            "value": ["<value>"],
            "operator": PropertyOperator.<Operator>  // e.g., PropertyOperator.Exact or PropertyOperator.IContains
            }
        ]
        }
    ]
    }
}
}
Notes
- Use FilterLogicalOperator.AND to ensure that all specified conditions must be met.
- The inner "values": [] array can include multiple filter items if needed.

2. Combining Filters with the OR Operator

When multiple conditions are acceptable (i.e., at least one must match), use the OR operator. The structure is similar, but with multiple groups in the outer array:

json
{
"data": {
    "date_from": "<date_from>",
    "date_to": "<date_to>",
    "duration": [{"key": "duration", "type": "recording", "value": <duration>, "operator": PropertyOperator.GreaterThan}],  // Use "gt", "lt", "gte", "lte"
    "filter_group": {
    "type": FilterLogicalOperator.OR,
    "values": [
        {
        "type": FilterLogicalOperator.AND,
        "values": [
            {
            "key": "<key>",
            "type": PropertyFilterType.<Type>,
            "value": ["<value>"],
            "operator": PropertyOperator.<Operator>
            }
        ]
        },
        {
        "type": FilterLogicalOperator.AND,
        "values": [
            {
            "key": "<key>",
            "type": PropertyFilterType.<Type>,
            "value": ["<value>"],
            "operator": PropertyOperator.<Operator>
            }
        ]
        }
    ]
    }
}
}

Notes:
- The outer group uses FilterLogicalOperator.OR, while each nested group uses FilterLogicalOperator.AND for its individual conditions.
- Multiple nested groups allow combining different filter criteria.

3. Operator Selection Guidelines

- Default Operators:
In most cases, the operator can be either exact or contains:
- For instance, if a user says, *"show me recordings where people visit login page"*, use the contains operator ("PropertyOperator.IContains") since the URL may include parameters.

- Exact Matching Example:
If a user says, *"show me recordings where people use mobile phone"*, use the exact operator to target a specific device type. For example:

json
{
    "data": {
    "date_from": "<date_from>",
    "date_to": "<date_to>",
    "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": PropertyOperator.GreaterThan}],
    "filter_test_accounts": "<boolean>",
    "filter_group": {
        "type": FilterLogicalOperator.AND,
        "values": [
        {
            "type": FilterLogicalOperator.AND,
            "values": [
            {
                "key": "$device_type",
                "type": PropertyFilterType.Person,
                "value": ["Mobile"],
                "operator": PropertyOperator.Exact
            }
            ]
        }
        ]
    }
    }
}

4. Special Cases

- Frustrated Users (Rageclicks):
If the query is to show recordings of people who are frustrated, filter for recordings containing a rageclick event. For example, use the event with:
- "id": "$rageclick", "name": "$rageclick", "type": "event"

- Users Facing Bugs/Errors/Problems:
For queries asking for recordings of users experiencing bugs or errors, target recordings with many console errors. An example filter might look like:
- Key: "level", Type: PropertyFilterType.Log_entry, Value: ["error"], Operator: PropertyOperator.Exact.

- Default Filter Group:
The blank, default `filter_group` value you can use is:

json
{
    "type": FilterLogicalOperator.AND,
    "values": [
        {
            "type": FilterLogicalOperator.AND,
            "values": []
        }
    ]
}

- Show all recordings / clean filters:
Return a default filter with default date range and no duration.

json
{
    "data":
    {
            "order": "start_time",
            "date_to": "null",
            "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": PropertyOperator.GreaterThan}],
            "date_from": "-3d",
            "filter_group": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            "filter_test_accounts": "true",
        }
}
</examples_and_rules>
""".strip()

PRODUCT_DESCRIPTION_PROMPT = """
PostHog (posthog.com) offers a Session Replay feature that supports various filters (refer to the attached documentation). Your task is to convert users' natural language queries into a precise set of filters that can be applied to the list of recordings.
""".strip()


FILTER_FIELDS_TAXONOMY_PROMPT = f"""
<taxonomy_info>
Below you will find information on how to correctly discover the taxonomy of the user's data.

<key> Field

- Purpose:
The <key> represents the name of the property on which the filter is applied.

- Type Determination:
The expected data type can be inferred from the property_type field provided in each property object:
- "String" indicates the value should be a string.
- "Numeric" indicates a numeric value.
- "Boolean" indicates a boolean value.
- "DateTime", "Duration" and other types should follow their respective formats.
- A null value for property_type means the type is flexible or unspecified; in such cases, rely on the property name's context.
</key>

<value> Field

- Purpose:
The <value> field is an array containing one or more values that the filter should match.

- Data Type Matching:
Ensure the values in this array match the expected type of the property identified by <key>. For example:
- For a property with property_type "String", the value should be provided as a string (e.g., ["Mobile"]).
- For a property with property_type "Numeric", the value should be a number (e.g., [10]).
- For a property with property_type "Boolean", the value should be either true or false (e.g., [true]).

- Multiple Values:
The <value> array can contain multiple items when the filter should match any one of several potential values.

<supported_operators>
Supported operators for the String or Numeric types are:
- equals
- doesn't equal
- contains
- doesn't contain
- matches regex
- doesn't match regex
- is set
- is not set

Supported operators for the DateTime type are:
- equals
- doesn't equal
- greater than
- less than
- is set
- is not set

Supported operators for the Boolean type are:
- equals
- doesn't equal
- is set
- is not set

All operators take a single value except for `equals` and `doesn't equal` which can take one or more values.
</supported_operators>


<list_of_property_and_event_names>
The following is a list of property names, event names and their definitions.
If you find the property name the user is asking for in the list, use it without calling a tool.
If you cannot find the property name in the list, call the tool to get the list of properties for the entity or event.


SOME OF THE AVAILABLE PROPERTIES, EVENTS and their definitions:
```json
{json.dumps(CORE_FILTER_DEFINITIONS_BY_GROUP, indent=2)}
```
#### SOME OF THE AVAILABLE CAMPAIGN PROPERTIES and their definitions:

```json
{json.dumps(CAMPAIGN_PROPERTIES, indent=2)}
```

</list_of_property_and_event_names>

</taxonomy_info>

""".strip()

PROPERTY_FILTER_TYPES_PROMPT = """
PostHog users can filter their data using various properties and values.
Properties are classified into groups based on the source of the property or a user defined group.
Each project has its own set of custom property groups, but there are also some core property groups that are available to all projects.
For example, properties can be belong to events, persons, actions, cohorts, sessions and more custom groups.
Properties can orginate from the following sources:
- Person Properties aka PersonPropertyFilter:
    Are associated with a person. For example, email, name, is_signed_up etc.
    Use the "name" field from the Person properties array (e.g. email).
    Example: If filtering on email, you might use the key email.
    Use `retrieve_entity_properties` to get the list of all available person properties.

- Session Properties aka SessionPropertyFilter:
    Are associated with a session. For example, $start_timestamp, $entry_current_url, session duration etc.
    Use the "name" field from the Session properties array (e.g., $start_timestamp, $entry_current_url).
    Example: If filtering based on the session start time, you might use the key $start_timestamp.
    Use `retrieve_entity_properties` to get the list of all available session properties.

- Event Properties aka EventPropertyFilter:
    Properties of an event. For example, $current_url, $browser, $ai_error etc
    Use the "name" field from the Event properties array (e.g. $current_url).
    Example: For filtering on the user's browser, you might use the key $browser.
""".strip()


TOOL_USAGE_PROMPT = """

## Tool Usage Rules
1. **Property Discovery Required**: Use tools to find properties.
2. Users can be looking for properties related to PERSON, SESSION, GROUP, or EVENT. EVENTS ARE NOT ENTITIES. THEY HAVE THEIR OWN PROPERTIES AND VALUES.

2. **Tool Workflow**:
   - Infer if the user is asking for a person, session, group, or event property.
   - Use `retrieve_entity_properties` to discover available properties for an entity such as person, session, organization, etc.
   - Use `retrieve_entity_property_values` to get possible values for a specific property related to person, session, organization, etc.
   - Use `retrieve_event_properties` to discover available properties for an event
   - Use `retrieve_event_property_values` to get possible values for a specific property related to event.
   - Use `ask_user_for_help` when you need clarification
   - Use `final_answer` only when you have complete filter information
   - *CRITICAL*: Call the event tools if you have found a property related to event, do not call the entity tools.
   - *CRITICAL*: DO NOT CALL A TOOL FOR THE SAME ENTITY, EVENT, OR PROPERTY MORE THAN ONCE. IF YOU HAVE NOT FOUND A MATCH YOU MUST TRY WITH THE NEXT BEST MATCH.

3. **Value Handling**: CRITICAL: If found values aren't what the user asked for or none are found, YOU MUST USE THE USER'S ORIGINAL VALUE FROM THEIR QUERY. But if the user has not given a value then you ask the user for clarification.

4. **Multi-Filter Example**: If user mentions "mobile users who completed signup":
   - Filter 1: Infer entity type "person" for "mobile" → find $device_type property → get values → use "Mobile"
   - Filter 2: Infer entity type "event" for "signup" → find $signup_event → get event properties if needed
   - Combine both filters with AND logic
   - Use `final_answer` only when ALL filters are processed

5. Use the output of the tools to build the filter. Merge the results for each filter component into a single filter.

""".strip()


FILTER_LOGICAL_OPERATORS_PROMPT = """
<filter_logical_operator>
The FilterLogicalOperator
- Defines how filters should be combined.
- Allowed Values: 'AND' or 'OR'

Property Filter Type aka PropertyFilterType
- Definition: The PropertyFilterType specifies the type of property to filter on.
- Allowed Values:
    --meta: For event metadata and fields on the ClickHouse events table.
    --event: For event properties aka EventPropertyFilter
    --person: For person properties aka PersonPropertyFilter
    --element: For element properties
    --session: For session properties aka SessionPropertyFilter
    --cohort: For cohorts.
    --recording: For recording properties aka RecordingPropertyFilter
    --log_entry: For log entry properties.
    --group: For group properties.
    --hogql: For hogql properties.
    --data_warehouse: For data warehouse properties.
    --data_warehouse_person_property: For data warehouse person properties.

Property Operator aka PropertyOperator
- Definition: The PropertyOperator defines the operator used for the comparison in a filter.
- Allowed Values:
    --Exact for 'exact'
    --IsNot for 'is_not'
    --IContains for 'icontains'
    --NotIContains for 'not_icontains'
    --Regex for 'regex'
    --NotRegex for 'not_regex'
    --GreaterThan for 'gt'
    --GreaterThanOrEqual for 'gte'
    --LessThan for 'lt'
    --LessThanOrEqual for 'lte'
    --IsSet     for 'is_set'
    --IsNotSet for 'is_not_set'
    --IsDateExact for 'is_date_exact'
    --IsDateBefore for 'is_date_before'
    --IsDateAfter for 'is_date_after'
    --Between for 'between'
    --NotBetween for 'not_between'
    --Minimum for 'min'
    --Maximum for 'max'
    --In for 'in'
    --NotIn for 'not_in'

</filter_logical_operator>
""".strip()

DATE_FIELDS_PROMPT = """
<date_fields>
Below is a refined description for the date fields and their types:

<date_from>
- Relative Date (Days): Use the format "-Nd" for the last N days (e.g., "last 5 days" becomes "-5d").
- Relative Date (Hours): Use the format "-Nh" for the last N hours (e.g., "last 5 hours" becomes "-5h").
- Custom Date: If a specific start date is provided, use the format "YYYY-MM-DD".
- If a date is provided but without a year or month, use the current year and month.
- Default Behavior: If the user does not specify a date range, default to the last 5 days (i.e., use "-5d"). date_from MUST be set.
</date_from>

<date_to>
- Default Value: Set as null when the date range extends to today. Set as null when the user does not specify an end date.
- Custom Date: If a specific end date is required, use the format "YYYY-MM-DD".
</date_to>
</date_fields>
""".strip()

HUMAN_IN_THE_LOOP_PROMPT = """
When you need clarification or determines that additional information is required, you can use the `ask_user_for_help` tool.
**When to Ask for Help**:
   - Cannot infer the correct entity/group/event type
   - No properties found for the entity/group/event
   - Property values don't match user's request
   - Any ambiguity in the user's request
""".strip()
