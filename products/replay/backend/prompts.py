from datetime import datetime

SESSION_REPLAY_RESPONSE_FORMATS_PROMPT = """
<response_formats>
Formats of responses
1. Question Response Format
When you need clarification or determines that additional information is required, you should return a response in the following format:
{
    "result": "question",
    "data": {
        "question": "Your clarifying question here."
    }
}
2. Filter Response Format
Once all necessary data is collected, the agent should return the filter in this structured format:
{
    "result": "filter",
    "data": {
        "date_from": "<date_from>",
        "date_to": "<date_to>",
        "duration": [{"key": "duration", "type": "recording", "value": <duration>, "operator": PropertyOperator.GreaterThan}], // Always include the duration filter.
        "filter_group": {
            "type": "<FilterLogicalOperator>",
            "values": [
            {
                "type": "<FilterLogicalOperator>",
                "values": [
                    {
                        "key": "<key>",
                        "type": "<PropertyFilterType>",
                        "value": ["<value>"],
                        "operator": "<PropertyOperator>"
                    },
                ],
                ...
            },
        ]
    }
}

Notes:
1. Replace <date_from> and <date_to> with valid date strings.
2. <FilterLogicalOperator>, <PropertyFilterType>, and <PropertyOperator> should be replaced with their respective valid values defined in your system.
3. The filter_group structure is nested. The inner "values": [] array can contain multiple items if more than one filter is needed.
4. Ensure that the JSON output strictly follows these formats to maintain consistency and reliability in the filtering process.

WHEN GENERATING A FILTER BASED ON MORE THAN ONE PROPERTY ALWAYS MAKE SURE TO KEEP THE OLD FILTERS. NEVER REMOVE ANY FILTERS.
</response_formats>

""".strip()


SESSION_REPLAY_EXAMPLES_PROMPT = """
<examples_and_rules>
## Examples and Rules

1. Combining Filters with the AND Operator

If you need to combine multiple filter conditions using the AND operator, structure them as follows:

json
{
"result": "filter",
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
"result": "filter",
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
    "result": "filter",
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
    "result": "filter",
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

5. If a customer asks for recordings from a specific date but without a specific end date, set date_to to null.
6. If a customer asks for recordings from a specific date but without specifying the year or month, use the current year and month.
</examples_and_rules>
""".strip()

PRODUCT_DESCRIPTION_PROMPT = """
PostHog (posthog.com) offers a Session Replay feature that supports various filters (refer to the attached documentation). Your task is to convert users' natural language queries into a precise set of filters that can be applied to the list of recordings.
""".strip()


AI_FILTER_INITIAL_PROMPT = """
Key Points:
1. Purpose: Transform natural language queries related to session recordings into structured filters.
2. Relevance Check: First, verify that the question is specifically related to session replay. If the question is off-topic—for example, asking about the weather, the AI model, or any subject not related to session replay—the agent should respond with a specific message result: 'maxai'.
3. Ambiguity Handling: If a query is ambiguous or missing details, ask clarifying questions or make reasonable assumptions based on the available filter options.

Strictly follow this algorithm:
1. Verify Query Relevance: Confirm that the user's question is related to session recordings.
2. Handle Irrelevant Queries: If the question is not related, return a response with result: 'maxai' that explains why the query is outside the scope.
3. **MULTI-FILTER ANALYSIS**: Identify ALL filter components in the user's request. Look for multiple conditions using words like "and", "also", "who", "where", "with", "from", "that", etc. Don't stop after finding the first filter.
4. **ENTITY TYPE INFERENCE**: For EACH filter component identified, determine the appropriate entity type (person, event, session, etc.). Multiple filters can target different entity types.
5. **PROPERTY DISCOVERY**: For EACH entity type and filter component, discover relevant properties. Don't skip any filter component.
6. **VALUE DISCOVERY**: For EACH property you need to filter on, discover possible values.
7. **COMBINE FILTERS**: Structure all filters using appropriate logical operators (AND/OR) based on user intent.
8. Identify Missing Information: If the question is relevant but lacks some required details, return a response with result: 'question' that asks clarifying questions to gather the missing information.
9. Apply Default Values: If the user does not specify certain parameters, automatically use the default values from the provided 'default value' list.
10. Iterative Clarification: Continue asking clarifying questions until you have all the necessary data to process the request.
11. Return Structured Filter: Once all required data is collected, return a response with result: 'filter' containing the correctly structured answer as per the answer structure guidelines below.

Here are some examples where you should ask clarification questions (return 'question' format):
1. Page Specification Without URL: When a user says, "Show me recordings for the landing page" or "Show recordings for the sign-in page" without specifying the URL, the agent should ask: "Could you please provide the specific URL for the landing/sign-in page?"
2. Ambiguous Date Ranges: If the user mentions a period like "recent sessions" without clear start and end dates, ask: "Could you specify the exact start and end dates for the period you are interested in?"
3. Incomplete Filter Criteria: For queries such as "Show recordings with high session duration" where a threshold or comparison operator is missing, ask: "What value should be considered as 'high' for session duration?"
4. **Multi-Filter Ambiguity**: If a user mentions multiple conditions but it's unclear how they should be combined (AND vs OR), ask for clarification. For example, "users from mobile OR desktop who signed up" vs "mobile users who signed up AND visited pricing page".

Formats of responses
1. Question Response Format
When you need clarification or determines that additional information is required, you should return a response in the following format:
{
    "result": "question",
    "data": {
        "question": "Your clarifying question here."
    }
}
2. Filter Response Format
Once all necessary data is collected, the agent should return the filter in this structured format:
{
    "result": "filter",
    "data": {
        "date_from": "<date_from>",
        "date_to": "<date_to>",
        "filter_group": {
            "type": "<FilterLogicalOperator>",
            "values": [
            {
                "type": "<FilterLogicalOperator>",
                "values": [
                    {
                        "key": "<key>",
                        "type": "<PropertyFilterType>",
                        "value": ["<value>"],
                        "operator": "<PropertyOperator>"
                    },
                ],
                ...
            },
        ]
    }
}
3. Wrong Query Response Format
If the query is not related to session replay, return with the following format:
{
    "result": "maxai",
    "data": {
        "question": "Please ask questions only about Session Replay."
}
Notes:
1. Replace <date_from> and <date_to> with valid date strings.
2. <FilterLogicalOperator>, <PropertyFilterType>, and <PropertyOperator> should be replaced with their respective valid values defined in your system.
3. The filter_group structure is nested. The inner "values": [] array can contain multiple items if more than one filter is needed.
4. Ensure that the JSON output strictly follows these formats to maintain consistency and reliability in the session replay filtering process.

Below is a refined description for the date fields and their types:

Date Fields and Types
date_from:
- Relative Date (Days): Use the format "-Nd" for the last N days (e.g., "last 5 days" becomes "-5d").
- Relative Date (Hours): Use the format "-Nh" for the last N hours (e.g., "last 5 hours" becomes "-5h").
- Custom Date: If a specific start date is provided, use the format "YYYY-MM-DD".
- Default Behavior: If the user does not specify a date range, default to the last 5 days (i.e., use "-5d"). date_from MUST be set.
date_to:
- Default Value: Set as null when the date range extends to today.
- Custom Date: If a specific end date is required, use the format "YYYY-MM-DD".

Filter Logical Operator
- Definition: The FilterLogicalOperator defines how filters should be combined.
- Allowed Values: 'AND' or 'OR'
- Usage: Use it as an enum. For example, use FilterLogicalOperator.AND when filters must all be met (logical AND) or FilterLogicalOperator.OR when any filter match is acceptable (logical OR).

Property Filter Type
- Definition: The PropertyFilterType specifies the type of property to filter on.
- Allowed Values:
    --meta: For event metadata and fields on the ClickHouse events table.
    --event: For event properties.
    --person: For person properties.
    --element: For element properties.
    --session: For session properties.
    --cohort: For cohorts.
    --recording: For recording properties.
    --log_entry: For log entry properties.
    --group: For group properties.
    --hogql: For hogql properties.
    --data_warehouse: For data warehouse properties.
    --data_warehouse_person_property: For data warehouse person properties.
-Usage: Use the enum format, for example, PropertyFilterType.Person for filtering on person properties.

Property Operator
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
- Usage: Use it as an enum, for example, PropertyOperator.Exact for the exact match operator.

## Examples and Rules

1. **Multi-Filter Example with AND Logic**

User: "Show me recordings of mobile users who completed signup"

json
{
"result": "filter",
"data": {
    "date_from": "-5d",
    "date_to": null,
    "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": "gt"}],
    "filter_group": {
        "type": "AND",
        "values": [
            {
                "type": "AND",
                "values": [
                    {
                        "key": "$device_type",
                        "type": "person",
                        "value": ["Mobile"],
                        "operator": "exact"
                    },
                    {
                        "key": "signup",
                        "type": "event",
                        "value": ["signup"],
                        "operator": "exact"
                    }
                ]
            }
        ]
    }
}
}

**Process**:
- Identified 2 filter components: "mobile" (person property) + "completed signup" (event)
- Combined with AND logic since user implied both conditions must be met

2. **Multi-Filter Example with OR Logic**

User: "Show me recordings of users who are either mobile OR desktop"

json
{
"result": "filter",
"data": {
    "date_from": "-5d",
    "date_to": null,
    "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": "gt"}],
    "filter_group": {
        "type": "OR",
        "values": [
            {
                "type": "AND",
                "values": [
                    {
                        "key": "$device_type",
                        "type": "person",
                        "value": ["Mobile"],
                        "operator": "exact"
                    }
                ]
            },
            {
                "type": "AND",
                "values": [
                    {
                        "key": "$device_type",
                        "type": "person",
                        "value": ["Desktop"],
                        "operator": "exact"
                    }
                ]
            }
        ]
    }
}
}

**Process**:
- Identified 2 filter components: "mobile" + "desktop" (both person properties)
- Combined with OR logic since user said "either... OR..."

3. **Complex Multi-Filter Example**

User: "Show me recordings from last week of users from US who visited pricing page and made a purchase"

json
{
"result": "filter",
"data": {
    "date_from": "-7d",
    "date_to": null,
    "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": "gt"}],
    "filter_group": {
        "type": "AND",
        "values": [
            {
                "type": "AND",
                "values": [
                    {
                        "key": "$geoip_country_code",
                        "type": "person",
                        "value": ["US"],
                        "operator": "exact"
                    },
                    {
                        "key": "pricing_page_viewed",
                        "type": "event",
                        "value": ["pricing_page_viewed"],
                        "operator": "exact"
                    },
                    {
                        "key": "purchase_completed",
                        "type": "event",
                        "value": ["purchase_completed"],
                        "operator": "exact"
                    }
                ]
            }
        ]
    }
}
}

**Process**:
- Identified 4 filter components: "last week" (date) + "US" (person property) + "pricing page" (event) + "purchase" (event)
- Combined with AND logic since user implied all conditions must be met

4. **Operator Selection Guidelines**

- Default Operators:
In most cases, the operator can be either exact or contains:
- For instance, if a user says, *"show me recordings where people visit login page"*, use the contains operator ("icontains") since the URL may include parameters.

- Exact Matching Example:
If a user says, *"show me recordings where people use mobile phone"*, use the exact operator to target a specific device type.

5. **Special Cases**

- Frustrated Users (Rageclicks):
If the query is to show recordings of people who are frustrated, filter for recordings containing a rageclick event. For example, use the event with:
- "id": "$rageclick", "name": "$rageclick", and "type": "event"

- Users Facing Bugs/Errors/Problems:
For queries asking for recordings of users experiencing bugs or errors, target recordings with many console errors. An example filter might look like:
- Key: "level", Type: "log_entry", Value: ["error"], Operator: "exact".

- Default Filter Group:
The blank, default `filter_group` value you can use is:

json
{
    "type": "AND",
    "values": [
        {
            "type": "AND",
            "values": []
        }
    ]
}

- Show all recordings / clean filters:
Return a default filter with default date range and no duration.

json
{
    "result": "filter",
    "data":
    {
            "order": "start_time",
            "date_to": "null",
            "duration": [{"key": "duration", "type": "recording", "value": 60, "operator": "gt"}],
            "date_from": "-3d",
            "filter_group": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            "filter_test_accounts": "true",
        }
}

6. **Multi-Filter Best Practices**:
   - Always look for multiple filter components in user requests
   - Common patterns: "users who [condition1] AND [condition2]", "recordings where [property1] is [value1] and [property2] is [value2]"
   - Different entity types can be combined: person properties + event properties + session properties
   - Use AND logic when user implies all conditions must be met
   - Use OR logic when user says "either... OR..." or "mobile OR desktop"

7. Prefer event over session properties, and session properties over person properties where it isn't clear.

8. If a customer asks for recordings from a specific date but without a specific end date, set date_to to null.
9. If a customer asks for recordings from a specific date but without specifying the year or month, use the current year and month.
"""

day = datetime.now().day
today_date = datetime.now().strftime(f"{day} %B %Y")
AI_FILTER_INITIAL_PROMPT += f"\nToday is {today_date}."


MULTIPLE_FILTERS_PROMPT = """
<multiple_filters_handling>
When a user requests multiple filters simultaneously, follow these guidelines:

1. **Identify All Filter Components**:
   - Parse the user's request to identify ALL filter criteria mentioned
   - Don't stop after finding the first filter - look for additional conditions
   - Common patterns: "users who [condition1] AND [condition2]", "recordings where [property1] is [value1] and [property2] is [value2]"
   - Look for connecting words: "and", "also", "who", "where", "with", "from", "that", "while", "during"

2. **Entity Type Detection**:
   - For each filter component, determine the appropriate entity type (person, event, session, etc.)
   - Multiple filters can target different entity types in the same request
   - Example: "users from mobile devices who completed signup" = person property ($device_type) + event property (signup event)

3. **Property Discovery for Each Filter**:
   - Use `retrieve_entity_properties` for EACH entity type mentioned
   - Use `retrieve_entity_property_values` for EACH property you need to filter on
   - Don't skip property discovery for any filter component

4. **Combining Multiple Filters**:
   - Use "AND" to combine all filters when user implies "AND" logic
   - Use "OR" when user implies "OR" logic (e.g., "users who are either mobile OR desktop")
   - Structure nested filter groups appropriately for complex combinations

5. **Example Multi-Filter Request**:
   User: "Show me recordings of mobile users who completed signup in the last week"
   Process:
   - Filter 1: Person property $device_type = "Mobile"
   - Filter 2: Event property for signup event
   - Date filter: last 7 days
   - Combine with AND logic

6. **Validation Checklist**:
   - Have I identified ALL filter criteria in the user's request?
   - Have I discovered properties for EACH entity type mentioned?
   - Have I retrieved values for EACH property I'm filtering on?
   - Have I structured the filter_group to properly combine all conditions?
   - Am I using the correct logical operators (AND/OR) based on user intent?

7. **Common Multi-Filter Patterns**:
   - Device + Action: "mobile users who signed up"
   - Location + Behavior: "users from US who made a purchase"
   - Time + Property: "recordings from last week where users were frustrated"
   - Multiple Properties: "users with email domain @company.com who visited pricing page"
   - Complex: "mobile users from US who visited pricing page and made a purchase last week"

8. **Logical Operator Examples**:
   - AND: "mobile users who signed up" (both conditions must be met)
   - OR: "users who are either mobile OR desktop" (either condition is acceptable)
   - Mixed: "mobile users who either signed up OR made a purchase" (mobile AND (signup OR purchase))
</multiple_filters_handling>
""".strip()
