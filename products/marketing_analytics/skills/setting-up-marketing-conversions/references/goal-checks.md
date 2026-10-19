# Goal definition and preview checks

## Business outcome and counting entity

Keep the requested outcome, counted entity, and attribution identity separate.
A business may define a customer as a person, household, account, store, or another entity.
Use the project's definition and observed schema. An activation, signup, trial, signed agreement, and first settled payment are different outcomes.
Do not relabel one as another to fill a missing dashboard metric.
When the request counts business objects and the audit verifies one event per object, use `total`. When it requests distinct people, use `dau`.
`dau` always counts people, never unique accounts, workspaces, or other groups. A person identity used for attribution does not change the counted entity.
Keep the supplied scope filters when narrowing an action to its relevant event; this does not create a new choice about which objects count.

This preview supports person attribution for both counts and revenue.
When assigning account or group transactions to a person, an approved allocation policy and a verified mapping to actual project people are separate requirements; neither implies the other.
A group-level attribution or CAC request remains unsupported even if its events contain person IDs or its source has one row per group.
Never replace unique groups with unique people, divide people by an average group size, or choose an arbitrary member as the attributed buyer.
Deduplicating a source to one row per group does not make unique-person math count groups: the same person may represent more than one group.
An approved contact policy can support attributing a transaction to a verified person. It does not turn that person's journey into native group attribution or establish group acquisition counts.

A bounded history query can establish only that no earlier record was observed in that history.
For first-ever customers, require an authoritative first-conversion marker or a complete historical source with a stated coverage boundary.
Otherwise label the measure as first observed in the covered period and ask whether that definition meets the business need.
When authoritative evidence already identifies each person's first payment, retain that filter and enable `counts_as_customer` for the requested customer goal. Another lifetime export is unnecessary.
For a bounded engagement definition, repeated events with `dau` need no first-ever marker. A total count of transactions and a unique-person count can coincide when there is exactly one qualifying record per person, but neither supplies missing first-payment evidence.

## Transaction identity

Inspect whether events represent distinct transactions, delivery retries, fan-out to multiple people, or successive snapshots.
For transaction revenue, require a stable transaction identifier and verify its coverage, scope, and conflicting amounts/statuses.
An account and a calendar day, an amount, or a person alone is not a transaction key.
Multiple legitimate payments can share any of those values. Do not use those combinations to publish a corrected revenue total.

Event/action sum goals do not deduplicate by a transaction property.
If duplicates are present, keep the goal blocked until instrumentation emits one record per transaction or a verified source/view resolves that identity.
Describe the required view and fields; do not claim it already exists or create it during a read-only recommendation.
Every new or corrected source proposal must cover its row grain, stable conversion ID, conversion timestamp, supported person mapping, and retained scope/project filters together. This includes event instrumentation, joins, and saved views.
Revenue also needs the monetary meaning, amount, documented units, and currency. Count goals do not need monetary fields.
State which parts are verified and which the proposed source must supply. An unstated field is unknown; do not claim it is verified or absent.
For account-only sources, require both an approved person-allocation policy and a verified mapping to people before claiming person attribution is supported.
Materialization changes performance and freshness, not the correctness of a deduplication rule.

## Revenue meaning

Resolve whether the requested measure is paid revenue, invoiced revenue, booked sales, or another explicitly chosen definition.
Inspect unresolved status filters, gross versus net amounts, taxes, refunds, and repeated payments only when they change the requested definition.
A source explicitly described as signed amounts including refunds already establishes that refund-inclusion choice. Carry it forward rather than asking the user to choose gross versus net again.
Separate refund or adjustment records do not establish their table or event stream. Keep an unknown storage location unknown; question inclusion only when the proposed source's refund coverage is unresolved.
Do not mark row grain or conversion timestamps verified merely because a record is described as paid or settled.
A field called `amount`, an event name, or a successful preview is insufficient evidence by itself.
Numeric IDs, file sizes, and subscription balance snapshots are not transaction amounts.

Confirm amount units from project knowledge or documentation. USD cents need a transformation before this preview; `math_multiplier` is rejected.
Use `math_property_revenue_currency` with `static` for a known fixed currency or `property` for a verified event currency property, following the tool schema.
If no currency is specified, the amount is assumed to be in the project base currency.
Missing or empty row currencies also fall back to the base currency. Inspect their prevalence before describing the result as validated revenue.
A fallback does not prove either the correct or the wrong currency was used; the missing rows' actual currency is unknown. Do not label every missing currency as an incorrect conversion.
This row-level fallback applies to a currency-property mapping, not a verified static currency.
A verified static currency describes the source amounts and need not equal the project reporting currency. Do not infer an error multiplier or conversion divisor without documented units.
Do not infer dollars from a numeric range or treat mixed-currency raw totals as comparable.

A negative amount may represent a refund. Summing signed amounts can reduce value while still counting that row as a conversion.
Refunds emitted as a different event do not reduce a payment-only goal unless its definition includes them.
When those semantics do not match the requested outcome, describe the limitation and the needed source change.
Filtering to positive amounts can remove refunds or credits; it is not a general revenue-cleaning rule.
Recurring revenue is valid when requested. Do not automatically remove renewals or claim that their inclusion inflates ROAS.
Distinguish acquisition-only revenue from lifecycle revenue and state the attribution model and window used for either.

## Attribution and filters

Identity resolution, direct UTM coverage, and journey attribution measure different things.
An identified person does not prove a matched acquisition session. Initial referrer/UTM properties do not prove website visits or missing attribution.
Use the preview's actual journey results for attribution claims; otherwise report coverage as unmeasured. This applies to engagement and customer counts as well as revenue.

Use the project's configured filters through supported query fields and preserve action URL, host, and property conditions in drafts and proposed source corrections. Include the project filters, attribution model/window, and observation period when recommending any future preview.
Do not silently reconstruct cohort membership or claim current-person semantics for an event-time property query.
If a source cannot support the required filters, report the incompatibility instead of dropping them.

## Preview scope

The preview uses attribution-table journey semantics and returns total, evaluated, attributed, and unattributed counts and values.
It does not reproduce Ad performance's direct UTM matching or establish that spend data is available for ROAS.
Event/action counts follow the existing event matching semantics; they do not deduplicate transactions by an order ID property.
An action preserves its filters, but overlapping goals can still represent the same transaction.

Count goals have null value fields. Revenue uses the project base currency.
Missing or nonnumeric event amounts can become zero through the existing amount fallback. A numeric total does not prove amount completeness.
When amounts can have either sign, missing values can overstate or understate the true total. Do not call the observed value a lower bound unless separate evidence establishes that bound.
Unique-user mode counts the first conversion in the selected window, not a person's first-ever purchase.
Group aggregation is unsupported.

Per-person conversion caps can leave rows unevaluated. Then total and unattributed values can be null while evaluated and attributed values describe only the evaluated subset.
Touchpoint caps can make attribution approximate. Keep all cap warnings beside the recommendation.
The returned observation time is the preview completion time, not a source freshness check.

The response explicitly lists checks not performed, including source quality, timestamps outside the range, native-currency breakdown, currency/rate validation, identity match coverage, source freshness, and business-definition validation.
Use separate bounded evidence for checks relevant to the decision or explain that they remain unresolved.
Do not present unchecked fields as zero errors, zero missing identities, or a completed validation.
