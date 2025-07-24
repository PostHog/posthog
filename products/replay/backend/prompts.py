# SESSION_REPLAY_RESPONSE_FORMATS_PROMPT = """
# <response_formats>
# Formats of responses
# 1. Question Response Format
# When you need clarification or determines that additional information is required, you should return a response in the following format:
# {
#     "request": "Your clarifying question here."
# }

# Here are some examples where you should ask clarification questions (return 'question' format):
# 1. Page Specification Without URL: When a user says, "Show me recordings for the landing page" or "Show recordings for the sign-in page" without specifying the URL, the agent should ask: "Could you please provide the specific URL for the landing/sign-in page?"
# 2. Ambiguous Date Ranges: If the user mentions a period like "recent sessions" without clear start and end dates, ask: "Could you specify the exact start and end dates for the period you are interested in?"
# 3. Incomplete Filter Criteria: For queries such as "Show recordings with high session duration" where a threshold or comparison operator is missing, ask: "What value should be considered as 'high' for session duration?"


# 2. Filter Response Format
# Once all necessary data is collected, the agent should return the filter in this structured format:
# {
#     "data": {
#         "date_from": "<date_from>",
#         "date_to": "<date_to>",
#         "duration": [{"key": "duration", "type": "recording", "value": <duration>, "operator": PropertyOperator.GreaterThan}], // Always include the duration filter.
#         "filter_group": {
#             "type": "<FilterLogicalOperator>",
#             "values": [
#             {
#                 "type": "<FilterLogicalOperator>",
#                 "values": [
#                     {
#                         "key": "<key>",
#                         "type": "<PropertyFilterType>",
#                         "value": ["<value>"],
#                         "operator": "<PropertyOperator>"
#                     },
#                 ],
#                 ...
#             },
#         ]
#     }
# }

# Notes:
# 1. Replace <date_from> and <date_to> with valid date strings.
# 2. <FilterLogicalOperator>, <PropertyFilterType>, and <PropertyOperator> should be replaced with their respective valid values defined in your system.
# 3. The filter_group structure is nested. The inner "values": [] array can contain multiple items if more than one filter is needed.
# 4. Ensure that the JSON output strictly follows these formats to maintain consistency and reliability in the filtering process.


# WHEN GENERATING A FILTER ALWAYS MAKE SURE TO KEEP THE STATE OF THE FILTERS. NEVER REMOVE ANY FILTERS UNLESS THE USER ASKS FOR IT.
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
<product_description>
PostHog (posthog.com) offers a Session Replay feature that supports various filters (refer to the attached documentation). Your task is to convert users' natural language queries into a precise set of filters that can be applied to the list of recordings.
</product_description>
""".strip()

FILTER_FIELDS_TAXONOMY_PROMPT = """
<filter_fields_taxonomy>
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

</filter_fields_taxonomy>

""".strip()


TOOL_USAGE_PROMPT = """
<tool_usage>
## Tool Usage Rules
1. **Property Discovery Required**: Use tools to find properties.
2. **CRITICAL DISTINCTION**: EVENTS ARE NOT ENTITIES. THEY HAVE THEIR OWN PROPERTIES AND VALUES.

3. **Tool Workflow**:
   - **For ENTITY properties** (person, session, organization, groups): Use `retrieve_entity_properties` and `retrieve_entity_property_values`
   - **For EVENT properties** (properties of specific events like pageview, signup, etc.): Use `retrieve_event_properties` and `retrieve_event_property_values`
   - Use `ask_user_for_help` when you need clarification
   - Use `final_answer` only when you have complete filter information
   - *CRITICAL*: NEVER use entity tools for event properties. NEVER use event tools for entity properties.
   - *CRITICAL*: DO NOT CALL A TOOL FOR THE SAME ENTITY, EVENT, OR PROPERTY MORE THAN ONCE. IF YOU HAVE NOT FOUND A MATCH YOU MUST TRY WITH THE NEXT BEST MATCH.

3. **When to Ask for Help**:
   - No properties found for the entity/group
   - Cannot infer the correct entity/group type
   - Property values don't match user's request
   - Any ambiguity in the user's request

4. **Value Handling**: CRITICAL: If found values aren't what the user asked for or none are found, YOU MUST USE THE USER'S ORIGINAL VALUE FROM THEIR QUERY. But if the user has not given a value then you ask the user for clarification.

5. **Tool Selection Decision Tree**:
   - If the user mentions a property that belongs to a person (name, email, location, etc.) → use entity tools with entity="person"
   - If the user mentions a property that belongs to a session (duration, start time, etc.) → use entity tools with entity="session"
   - If the user mentions a property that belongs to a group (organization, account, etc.) → use entity tools with entity="[group_name]"
   - If the user mentions an action or event (signup, purchase, pageview, etc.) → use event tools with event_name="[event_name]"
</tool_usage>
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
- Relative Date (Days): Use the format "-Nd" for the last N days (e.g., "last 5 days" becomes "-5d", "yesterday" becomes "-1d").
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
