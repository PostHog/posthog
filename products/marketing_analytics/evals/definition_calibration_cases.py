from __future__ import annotations

from typing import Literal

from posthog.dataclasses import frozen

from products.posthog_ai.eval_harness.config import BaseEvalCase

CalibrationCheck = Literal[
    "criterion_coverage",
    "evidence_fidelity",
    "entity_semantics",
    "source_contract",
    "numeric_and_filter_fidelity",
    "review_scope",
]


@frozen
class _CalibrationPair:
    error_class: str
    audit: str
    criterion: str
    accepted_answer: str
    rejected_answer: str
    rejected_checks: tuple[CalibrationCheck, ...]


def definition_calibration_cases() -> list[BaseEvalCase]:
    pairs = [
        _CalibrationPair(
            error_class="journey_filter_omission",
            audit=(
                "A pottery studio records workshop_finished with a verified attendee person ID. "
                "The active report excludes staff and uses the previous 14 days. No session matching "
                "results are supplied. Someone says all completions are attributed because everyone "
                "is identified. Review that claim and describe the needed measurement."
            ),
            criterion=(
                "Reject the claimed attribution percentage and keep journey coverage unknown. "
                "Propose a journey preview retaining both staff exclusion and the 14-day reporting window. "
                "Do not say a preview was executed."
            ),
            accepted_answer=(
                "Person identity alone does not tell us whether a completion has a matching journey. "
                "Coverage remains unknown. Measure it with a journey preview over the same preceding "
                "fortnight, still excluding staff. No such measurement is available in this review."
            ),
            rejected_answer=(
                "Person identity alone does not tell us whether a completion has a matching journey. "
                "Coverage remains unknown. Measure it with a journey preview over the same preceding "
                "fortnight. No such measurement is available in this review."
            ),
            rejected_checks=("criterion_coverage", "numeric_and_filter_fidelity"),
        ),
        _CalibrationPair(
            error_class="transaction_example_arithmetic",
            audit=(
                "A telescope retailer has charges X1 for 17 CHF and X2 for 26 CHF. Both happened for "
                "one buyer on one calendar day. Each charge was delivered twice with identical "
                "values. A charge-keyed warehouse view is proposed but does not yet exist. Review "
                "the correct revenue and the fields that proposed view would need."
            ),
            criterion=(
                "Preserve two distinct charges totaling 43 CHF and distinguish them from one buyer-day. "
                "Reject summing retry rows. Keep the proposed view conditional on verified charge identity, "
                "settlement timestamp, CHF amount, and supported buyer person mapping."
            ),
            accepted_answer=(
                "The two charges contribute 17 + 26 = 43 CHF. They share one buyer-day, so that key "
                "would collapse legitimate charges. Raw retry rows must not be summed. A future view "
                "must verify one row per charge, its settlement time and CHF amount, plus a supported "
                "buyer-to-person mapping. That source remains proposed."
            ),
            rejected_answer=(
                "The two charges contribute 17 + 26 = 43 CHF. They represent two buyer-days, so that "
                "key would preserve both charges. Raw retry rows must not be summed. A future view "
                "must verify one row per charge, its settlement time and CHF amount, plus a supported "
                "buyer-to-person mapping. That source remains proposed."
            ),
            rejected_checks=("criterion_coverage", "evidence_fidelity", "numeric_and_filter_fidelity"),
        ),
        _CalibrationPair(
            error_class="missing_person_mapping",
            audit=(
                "A repair workshop receives duplicate repair_paid deliveries. The audit verifies "
                "repair_payment_key, paid_at, and received_aud in AUD units. It supplies an account "
                "code but no mapping to a person. The destination attributes only to people. Describe "
                "a conditional warehouse source that could support collected revenue."
            ),
            criterion=(
                "Propose one verified row per repair_payment_key retaining paid_at and received_aud "
                "with AUD currency. Make a supported person mapping an explicit prerequisite. An account "
                "code alone is insufficient. Keep the goal conditional and do not claim source creation."
            ),
            accepted_answer=(
                "A conditional source would remove delivery duplicates by repair_payment_key and keep "
                "paid_at and received_aud, interpreted as AUD. Before it can support a goal, verify "
                "the resulting row identity, approve an attribution policy for accounts, and establish "
                "a supported mapping to a person; "
                "the account code does not supply that mapping. This source has not been created."
            ),
            rejected_answer=(
                "A conditional source would remove delivery duplicates by repair_payment_key and keep "
                "paid_at and received_aud, interpreted as AUD. Before it can support a goal, verify "
                "the resulting row identity. The account code can be retained as a reference field. "
                "This source has not been created."
            ),
            rejected_checks=("criterion_coverage", "source_contract"),
        ),
        _CalibrationPair(
            error_class="group_person_substitution",
            audit=(
                "A seed distributor wants unique cooperative customers. Its source already has one "
                "activation row per cooperative, but a purchasing person may represent several "
                "cooperatives. The destination supports unique-person math and no group attribution. "
                "There is no approved cooperative attribution policy. Can unique people report this goal?"
            ),
            criterion=(
                "Keep the cooperative goal unsupported. One activation per cooperative does not make "
                "unique-person counting equivalent. Require a supported cooperative attribution design "
                "instead of claiming deduplication or a representative person resolves the limitation."
            ),
            accepted_answer=(
                "No. Unique people can merge several cooperatives represented by one buyer. The clean "
                "row grain does not solve that counting or attribution mismatch. Keep this cooperative "
                "goal unsupported until an explicitly supported cooperative attribution design exists."
            ),
            rejected_answer=(
                "Yes. Because the source has one activation row per cooperative, unique people will "
                "count cooperatives correctly even when the same buyer represents several of them. "
                "The existing deduplication makes this goal supported without another attribution design."
            ),
            rejected_checks=("criterion_coverage", "entity_semantics"),
        ),
        _CalibrationPair(
            error_class="invented_refund_location",
            audit=(
                "A furniture restorer wants net cash collected. Payment records contain signed values "
                "in NZD, and refunds are negative adjustments. The audit does not identify whether "
                "refund adjustments belong to the same event family. Review a positive-value-only "
                "filter without assuming where the refund records are stored."
            ),
            criterion=(
                "Reject positive-only filtering as a general net-cash rule. Preserve refund location "
                "as unknown and require evidence that the selected source includes relevant adjustments. "
                "Do not assert that refunds are in the same or a different event family."
            ),
            accepted_answer=(
                "Positive-only filtering is unsuitable as a general net-cash rule because it would discard "
                "any negative adjustments included in the selected source. Their event family is not "
                "specified. Confirm where those adjustments occur and ensure the chosen definition "
                "includes them before treating its sum as net collections."
            ),
            rejected_answer=(
                "Positive-only filtering is unsuitable as a general net-cash rule because it would discard "
                "any negative adjustments included in the selected source. Refunds are in a separate event "
                "family, as the audit establishes. Ensure the chosen definition includes that family "
                "before treating its sum as net collections."
            ),
            rejected_checks=("criterion_coverage", "evidence_fidelity"),
        ),
        _CalibrationPair(
            error_class="unknown_currency_declared_wrong",
            audit=(
                "A model-making shop uses SGD as its project base currency. Its revenue mapping reads "
                "row_currency, with the documented fallback to the base currency when the property "
                "is empty. Some rows have an empty property, and their actual currency is unknown. "
                "Does that establish that every affected amount was converted incorrectly?"
            ),
            criterion=(
                "Explain the SGD fallback without treating unknown currency as proof of correct or "
                "incorrect conversion. Require evidence about affected rows before quantifying an error."
            ),
            accepted_answer=(
                "No. Empty row_currency values use SGD here. Those rows may actually be SGD or may "
                "need another currency, so the fallback alone proves neither correctness nor an error. "
                "Establish the currencies and affected amounts before quantifying any misstatement."
            ),
            rejected_answer=(
                "Yes. Empty row_currency values use SGD here. Because their actual currency is "
                "unknown, every such row is necessarily misclassified. Establish the affected amounts "
                "before quantifying the misstatement."
            ),
            rejected_checks=("criterion_coverage", "evidence_fidelity"),
        ),
        _CalibrationPair(
            error_class="objects_counted_as_people",
            audit=(
                "An archive measures the number of digitization jobs completed. Verified action 814 "
                "matches scan_job_finished with review_state='accepted' and dataset='public'. Each "
                "job emits exactly one event tied to its operator, and one operator can finish many "
                "jobs. This is an activity count, with no revenue or customer designation. Review "
                "the action and counting method. No preview results are supplied."
            ),
            criterion=(
                "Reuse action 814 with both conditions and total event count for completed jobs. "
                "Do not substitute unique operators. Keep revenue and customer flags false and "
                "state that the draft has no measured preview."
            ),
            accepted_answer=(
                "Use action 814, retaining review_state='accepted' and dataset='public', with total "
                "counts. One event represents one completed job, while an operator can complete many. "
                "Both revenue and customer flags stay false. This draft has no preview measurement."
            ),
            rejected_answer=(
                "Use action 814, retaining review_state='accepted' and dataset='public', with unique "
                "operator counts. That measures completed jobs even when an operator completes many. "
                "Both revenue and customer flags stay false. This draft has no preview measurement."
            ),
            rejected_checks=("criterion_coverage", "entity_semantics"),
        ),
        _CalibrationPair(
            error_class="preview_required_for_definition",
            audit=(
                "A ceramics exporter requests a read-only review of net export collections. The "
                "supplied verified view export_cash has one row per entry_key, settled_at, signed_eur "
                "in EUR units including refunds, and a supported payer-to-person mapping. Required "
                "project filters are supported. No journey preview or spend data is supplied. Is "
                "the definition a supported draft, and can it establish marketing returns?"
            ),
            criterion=(
                "Accept a definition draft summing signed_eur with static EUR, revenue true and "
                "customer false. Do not make an executed preview a prerequisite for this definition-only "
                "judgment. Before measured returns, require journey evidence with preserved filters, "
                "model and window review, and compatible spend evidence. Claim no execution or returns."
            ),
            accepted_answer=(
                "This supports a draft sum of signed_eur in static EUR, with revenue enabled and "
                "customer disabled. That conclusion concerns the supplied definition only. Marketing "
                "returns remain unmeasured: later obtain a journey preview preserving project filters, "
                "review its attribution model and window, and establish compatible spend evidence."
            ),
            rejected_answer=(
                "The proposed draft is a sum of signed_eur in static EUR, with revenue enabled and "
                "customer disabled, but I cannot accept even its definition until a preview is run. "
                "Marketing returns remain unmeasured: later obtain a journey preview preserving project "
                "filters, review its attribution model and window, and establish compatible spend evidence."
            ),
            rejected_checks=("criterion_coverage", "review_scope"),
        ),
        _CalibrationPair(
            error_class="reopening_resolved_revenue_policy",
            audit=(
                "A puzzle subscription explicitly measures lifecycle collections, including renewal "
                "payments and signed refund entries. It accepts refund entries as conversion rows. "
                "The verified cash_entries view has entry_id, settled_at, signed_usd in dollar units, "
                "and a supported buyer person mapping. Review only the revenue definition; no marketing "
                "return is requested or measured."
            ),
            criterion=(
                "Propose sum of signed_usd with static USD and revenue enabled, keeping renewals and "
                "refund entries under the stated policy. Keep customer counting separate. Do not make "
                "reconfirming those accepted choices a prerequisite or invent a measured return."
            ),
            accepted_answer=(
                "Use the verified cash_entries view to sum signed_usd in static USD as revenue. "
                "Preserve renewal payments and signed refunds, including the accepted refund-row "
                "conversion behavior. Leave the customer flag off; this is not a first-customer "
                "measure. This review makes no claim about measured marketing returns."
            ),
            rejected_answer=(
                "Use the verified cash_entries view to sum signed_usd in static USD as revenue, "
                "but hold the definition until you confirm whether renewals and refund entries "
                "should count. Leave the customer flag off; this is not a first-customer measure. "
                "This review makes no claim about measured marketing returns."
            ),
            rejected_checks=("criterion_coverage", "evidence_fidelity", "review_scope"),
        ),
        _CalibrationPair(
            error_class="monetary_blocker_for_activity_count",
            audit=(
                "A climbing gym requests the number of completed route inspections, not fees or new "
                "customers. The audit verifies one route_inspection_done event per inspection, the "
                "condition result='passed', an event timestamp and an inspector person ID. No amount "
                "or currency is present. Review a total-count draft only; there is no preview evidence."
            ),
            criterion=(
                "Accept the total-count activity draft preserving result='passed', with revenue and "
                "customer flags false. Missing monetary fields do not block this count definition. "
                "Do not claim a preview occurred."
            ),
            accepted_answer=(
                "The supplied audit supports total counts of route_inspection_done where result='passed'. "
                "Set revenue and customer flags to false. Amount and currency are unnecessary for this "
                "requested activity count. The draft has not been previewed."
            ),
            rejected_answer=(
                "Use total counts of route_inspection_done where result='passed', with revenue and "
                "customer flags false. However, this definition must stay blocked until amount units "
                "and currency are documented. The draft has not been previewed."
            ),
            rejected_checks=("criterion_coverage", "review_scope"),
        ),
        _CalibrationPair(
            error_class="proposed_source_reported_created",
            audit=(
                "A language examiner wants net exam collections. The audit verifies one row per "
                "cash_entry_id, paid_at, signed_gbp_pence including refunds, and a supported payer "
                "person mapping. The target accepts currency units, not pence or a multiplier. "
                "There is no pounds-denominated source. Review the required transformation without "
                "performing any writes or queries."
            ),
            criterion=(
                "Keep direct pence summation unsupported. Describe a conditional transformation to "
                "GBP units retaining entry identity, paid_at, signed refunds, and payer mapping. "
                "Do not claim that the transformation was created, verified, or previewed."
            ),
            accepted_answer=(
                "Do not sum pence directly as pounds. A proposed source would divide signed_gbp_pence "
                "by 100 into GBP units, keeping one row per cash_entry_id, paid_at, signed refunds, and the payer "
                "person mapping. That source still needs to be built and verified; no transformation "
                "or preview has been performed here."
            ),
            rejected_answer=(
                "Do not sum pence directly as pounds. I created and verified a source dividing "
                "signed_gbp_pence by 100 into GBP units, keeping one row per cash_entry_id, paid_at, signed "
                "refunds, and the payer person mapping. No preview has been performed here."
            ),
            rejected_checks=("criterion_coverage", "evidence_fidelity", "review_scope"),
        ),
        _CalibrationPair(
            error_class="uncorrected_timestamp_claim",
            audit=(
                "A costume maker has a proposed revenue view with stable payment_ref, signed_cad "
                "in CAD units and a verified payer person mapping. Its only time column, loaded_at, "
                "is documented as batch import time, not settlement time. No suitable conversion "
                "timestamp is supplied. Review readiness without replacing the requested payment timing."
            ),
            criterion=(
                "Keep the source blocked on a verified settlement timestamp. Do not present loaded_at "
                "as that timestamp or claim the contract is complete. A clearly withdrawn earlier "
                "mistake does not invalidate an otherwise correct final recommendation."
            ),
            accepted_answer=(
                "I initially treated loaded_at as payment time; that was incorrect and I withdraw it. "
                "The audit says it is batch import time. Payment identity, CAD amount and payer mapping "
                "are established, but settlement time is not. Keep the source blocked until an appropriate "
                "settlement timestamp is supplied and verified."
            ),
            rejected_answer=(
                "The audit says loaded_at is batch import time rather than payment time. Payment "
                "identity, CAD amount and payer mapping are established. Nevertheless, loaded_at is "
                "a verified settlement timestamp, so the source contract is complete and the revenue "
                "definition is ready without another timestamp."
            ),
            rejected_checks=("criterion_coverage", "evidence_fidelity", "source_contract"),
        ),
    ]
    cases: list[BaseEvalCase] = []
    for pair in pairs:
        for gold_pass in (True, False):
            cases.append(
                BaseEvalCase(
                    name=f"calibration_{pair.error_class}_{'accepted' if gold_pass else 'rejected'}",
                    prompt="Review the supplied synthetic audit only. Do not query or save anything.\n\n" + pair.audit,
                    expected={"conversion_definition_evidence": {"criterion": pair.criterion}},
                    metadata={
                        "pair_id": pair.error_class,
                        "error_class": pair.error_class,
                        "answer": pair.accepted_answer if gold_pass else pair.rejected_answer,
                        "gold_pass": gold_pass,
                        "gold_failed_checks": [] if gold_pass else list(pair.rejected_checks),
                        "provenance": {
                            "kind": "independently_authored_synthetic",
                            "method": "Invented audits and answer pairs from general error classes, not transcripts.",
                            "label_source": "agent_authored_reference",
                        },
                    },
                )
            )
    return cases
