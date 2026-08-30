//! The gate on [`cohort_core::hogvm::analysis`]: a condition evaluated against only the globals the
//! analysis claimed it reads must reach the same verdict as one evaluated against the whole event.
//!
//! That is the property a caller relies on. If the claimed read set were ever short, a scan built
//! from it would hand the VM an event missing a value the condition needs, and the condition would
//! quietly decide the wrong way. Per-opcode unit tests cannot catch that, because the failure is a
//! disagreement between two whole evaluations rather than a wrong step.
//!
//! Every program here is synthesized from an AST by an emitter that mirrors the HogQL compiler's
//! output order. No bytecode is copied from a real catalog.

use std::collections::{BTreeMap, BTreeSet};

use cohort_core::events::CohortStreamEvent;
use cohort_core::hogvm::analysis::{analyze_condition, GlobalRoot, Projection, ReadPath};
use cohort_core::{build_behavioral_globals, evaluate_detailed, EvalOutcome};
use proptest::prelude::*;
use serde_json::{json, Value};

// Opcodes, named so the emitter reads like the compiler's output.
const OP_GET_GLOBAL: i64 = 1;
const OP_AND: i64 = 3;
const OP_OR: i64 = 4;
const OP_STRING: i64 = 32;
const OP_RETURN: i64 = 38;
const OP_TUPLE: i64 = 44;

/// A property key no generated condition ever reads. Every event carries it, so a projection that
/// leaked the whole property bag instead of the claimed keys would still pass; a projection that
/// dropped a claimed key would not.
const NOISE_KEYS: [&str; 3] = ["$browser", "$os", "unrelated"];

/// The property the globals fall back to when the elements-chain column is empty.
const ELEMENTS_CHAIN_PROPERTY: &str = "$elements_chain";

/// The event globals a generated condition may compare against.
#[derive(Debug, Clone, PartialEq, Eq)]
enum Field {
    Event,
    DistinctId,
    Timestamp,
    ElementsChain,
    Property(String),
    PersonProperty(String),
}

impl Field {
    /// The global chain, root first, as HogQL would write it.
    fn chain(&self) -> Vec<&str> {
        match self {
            Self::Event => vec!["event"],
            Self::DistinctId => vec!["distinct_id"],
            Self::Timestamp => vec!["timestamp"],
            Self::ElementsChain => vec!["elements_chain"],
            Self::Property(key) => vec!["properties", key],
            Self::PersonProperty(key) => vec!["person", "properties", key],
        }
    }
}

/// The comparison opcodes a cohort condition realistically compiles to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CmpOp {
    Eq = 11,
    NotEq = 12,
    Gt = 13,
    GtEq = 14,
    Lt = 15,
    LtEq = 16,
    Like = 17,
    ILike = 18,
    Regex = 23,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Expr {
    Compare {
        field: Field,
        op: CmpOp,
        literal: String,
    },
    InTuple {
        field: Field,
        options: Vec<String>,
    },
    All(Vec<Expr>),
    Any(Vec<Expr>),
}

/// Emit `expr` the way `posthog/hogql/compiler/bytecode.py` emits it.
///
/// Two orderings are load-bearing and are the reason this emitter exists rather than a hand-written
/// fixture. A comparison emits its right operand first, then its left, then the opcode. A global
/// chain is pushed leaf first, so `GET_GLOBAL` pops the root first.
fn emit(expr: &Expr) -> Vec<Value> {
    match expr {
        Expr::Compare { field, op, literal } => {
            let mut tokens = vec![json!(OP_STRING), json!(literal)];
            tokens.extend(emit_field(field));
            tokens.push(json!(*op as i64));
            tokens
        }
        Expr::InTuple { field, options } => {
            let mut tokens = Vec::new();
            for option in options {
                tokens.push(json!(OP_STRING));
                tokens.push(json!(option));
            }
            tokens.push(json!(OP_TUPLE));
            tokens.push(json!(options.len()));
            tokens.extend(emit_field(field));
            tokens.push(json!(21));
            tokens
        }
        Expr::All(exprs) => emit_combined(exprs, OP_AND),
        Expr::Any(exprs) => emit_combined(exprs, OP_OR),
    }
}

fn emit_combined(exprs: &[Expr], op: i64) -> Vec<Value> {
    let mut tokens = Vec::new();
    for expr in exprs {
        tokens.extend(emit(expr));
    }
    tokens.push(json!(op));
    tokens.push(json!(exprs.len()));
    tokens
}

fn emit_field(field: &Field) -> Vec<Value> {
    let chain = field.chain();
    let mut tokens = Vec::new();
    for segment in chain.iter().rev() {
        tokens.push(json!(OP_STRING));
        tokens.push(json!(segment));
    }
    tokens.push(json!(OP_GET_GLOBAL));
    tokens.push(json!(chain.len()));
    tokens
}

/// The loaded form: the header, the program, and the `RETURN` the catalog loader appends.
fn program(expr: &Expr) -> Vec<Value> {
    let mut bytecode = vec![json!("_H"), json!(1)];
    bytecode.extend(emit(expr));
    bytecode.push(json!(OP_RETURN));
    bytecode
}

/// A generated event. Held as fields rather than as built globals so it can be projected.
#[derive(Debug, Clone)]
struct TestEvent {
    event: String,
    distinct_id: String,
    timestamp: String,
    elements_chain: String,
    properties: BTreeMap<String, String>,
    person_properties: BTreeMap<String, String>,
}

impl TestEvent {
    fn to_stream_event(&self) -> CohortStreamEvent {
        CohortStreamEvent {
            team_id: 2,
            person_id: "01931234-0000-0000-0000-000000000001".to_owned(),
            distinct_id: self.distinct_id.clone(),
            uuid: "01931234-0000-0000-0000-0000000000ff".to_owned(),
            event: self.event.clone(),
            timestamp: self.timestamp.clone(),
            properties: Some(to_json_object(&self.properties)),
            person_properties: Some(to_json_object(&self.person_properties)),
            elements_chain: (!self.elements_chain.is_empty()).then(|| self.elements_chain.clone()),
            source_offset: 0,
            source_partition: -1,
            redirected_from: None,
            redirect_hops: 0,
        }
    }

    /// The event a scan built from `paths` would produce: everything the analysis did not claim is
    /// absent, exactly as a narrower `SELECT` would leave it.
    fn projected(&self, paths: &BTreeSet<ReadPath>) -> CohortStreamEvent {
        let mut projected = TestEvent {
            event: String::new(),
            distinct_id: String::new(),
            timestamp: String::new(),
            elements_chain: String::new(),
            properties: BTreeMap::new(),
            person_properties: BTreeMap::new(),
        };
        for path in paths {
            match (&path.root, path.segments.as_slice()) {
                (GlobalRoot::Event, []) => projected.event = self.event.clone(),
                (GlobalRoot::DistinctId, []) => projected.distinct_id = self.distinct_id.clone(),
                (GlobalRoot::Timestamp, []) => projected.timestamp = self.timestamp.clone(),
                (GlobalRoot::ElementsChain, []) => {
                    projected.elements_chain = self.elements_chain.clone();
                }
                (GlobalRoot::Properties, [key]) => {
                    if let Some(value) = self.properties.get(key) {
                        projected.properties.insert(key.clone(), value.clone());
                    }
                }
                (GlobalRoot::Person, [scope, key]) if scope == "properties" => {
                    if let Some(value) = self.person_properties.get(key) {
                        projected
                            .person_properties
                            .insert(key.clone(), value.clone());
                    }
                }
                other => panic!(
                    "the generator produced a read this harness cannot project: {other:?}. \
                     Extend `projected` before extending the generator."
                ),
            }
        }
        projected.to_stream_event()
    }
}

fn to_json_object(entries: &BTreeMap<String, String>) -> String {
    Value::Object(
        entries
            .iter()
            .map(|(key, value)| (key.clone(), Value::String(value.clone())))
            .collect(),
    )
    .to_string()
}

/// [`EvalOutcome`] flattened to something comparable, keeping enough detail that two different
/// failures are not read as agreement.
fn verdict(outcome: EvalOutcome) -> String {
    match outcome {
        EvalOutcome::Matched(matched) => format!("matched:{matched}"),
        EvalOutcome::UnknownFunction(name) => format!("unknown_function:{name}"),
        EvalOutcome::VmError(error) => format!("vm_error:{error:?}"),
    }
}

fn evaluate(bytecode: &[Value], event: &CohortStreamEvent) -> String {
    let globals = build_behavioral_globals(event).expect("generated payloads are valid JSON");
    verdict(evaluate_detailed(bytecode, globals))
}

// Small alphabets, so matches and non-matches both occur often. A generator over free-form strings
// would make almost every comparison false and stop exercising the matching path.
const VALUES: [&str; 5] = ["alpha", "beta", "gamma", "10", "2"];
const EVENT_NAMES: [&str; 3] = ["purchase", "$pageview", "signup"];
const PROPERTY_KEYS: [&str; 3] = ["plan", "country", "tier"];
const PERSON_KEYS: [&str; 2] = ["email", "role"];
const PATTERNS: [&str; 4] = ["%alpha%", "alpha", "a.*", "^beta$"];

fn field_strategy() -> impl Strategy<Value = Field> {
    prop_oneof![
        Just(Field::Event),
        Just(Field::DistinctId),
        Just(Field::Timestamp),
        Just(Field::ElementsChain),
        prop::sample::select(&PROPERTY_KEYS[..]).prop_map(|key| Field::Property(key.to_owned())),
        prop::sample::select(&PERSON_KEYS[..])
            .prop_map(|key| Field::PersonProperty(key.to_owned())),
    ]
}

fn leaf_strategy() -> impl Strategy<Value = Expr> {
    prop_oneof![
        (
            field_strategy(),
            prop_oneof![
                Just(CmpOp::Eq),
                Just(CmpOp::NotEq),
                Just(CmpOp::Gt),
                Just(CmpOp::GtEq),
                Just(CmpOp::Lt),
                Just(CmpOp::LtEq),
            ],
            prop::sample::select(&VALUES[..]),
        )
            .prop_map(|(field, op, literal)| Expr::Compare {
                field,
                op,
                literal: literal.to_owned(),
            }),
        (
            field_strategy(),
            prop_oneof![Just(CmpOp::Like), Just(CmpOp::ILike), Just(CmpOp::Regex)],
            prop::sample::select(&PATTERNS[..]),
        )
            .prop_map(|(field, op, literal)| Expr::Compare {
                field,
                op,
                literal: literal.to_owned(),
            }),
        (
            field_strategy(),
            prop::collection::vec(prop::sample::select(&VALUES[..]), 1..4),
        )
            .prop_map(|(field, options)| Expr::InTuple {
                field,
                options: options.into_iter().map(str::to_owned).collect(),
            }),
    ]
}

fn expr_strategy() -> impl Strategy<Value = Expr> {
    leaf_strategy().prop_recursive(3, 12, 3, |inner| {
        prop_oneof![
            prop::collection::vec(inner.clone(), 1..4).prop_map(Expr::All),
            prop::collection::vec(inner, 1..4).prop_map(Expr::Any),
        ]
    })
}

fn event_strategy() -> impl Strategy<Value = TestEvent> {
    (
        prop::sample::select(&EVENT_NAMES[..]),
        prop::sample::select(&VALUES[..]),
        prop::collection::vec(prop::sample::select(&VALUES[..]), PROPERTY_KEYS.len()),
        prop::collection::vec(prop::sample::select(&VALUES[..]), PERSON_KEYS.len()),
        prop::sample::select(&VALUES[..]),
        // Half the events leave the elements-chain column empty, which is what makes the globals
        // fall back to `properties.$elements_chain`. Without those cases the fallback the analysis
        // claims would never be exercised, and dropping the claim would go unnoticed.
        any::<bool>(),
    )
        .prop_map(
            |(event, distinct_id, property_values, person_values, chain, chain_in_column)| {
                let mut properties: BTreeMap<String, String> = PROPERTY_KEYS
                    .iter()
                    .zip(property_values)
                    .map(|(key, value)| ((*key).to_owned(), value.to_owned()))
                    .collect();
                // Keys no condition reads. A projection that dropped a claimed key fails; one that
                // kept these extra keys does not, which is the asymmetry this test wants.
                for noise in NOISE_KEYS {
                    properties.insert(noise.to_owned(), "noise".to_owned());
                }
                let rendered_chain = format!("a:href=\"/{chain}\"");
                let elements_chain = if chain_in_column {
                    rendered_chain
                } else {
                    properties.insert(ELEMENTS_CHAIN_PROPERTY.to_owned(), rendered_chain);
                    String::new()
                };
                TestEvent {
                    event: event.to_owned(),
                    distinct_id: distinct_id.to_owned(),
                    timestamp: "2026-05-26 12:34:56.789000".to_owned(),
                    elements_chain,
                    properties,
                    person_properties: PERSON_KEYS
                        .iter()
                        .zip(person_values)
                        .map(|(key, value)| ((*key).to_owned(), value.to_owned()))
                        .collect(),
                }
            },
        )
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(512))]

    /// The gate. For any generated condition the analysis narrows, evaluating it against only the
    /// claimed globals must reach the same verdict as evaluating it against the whole event.
    #[test]
    fn a_claimed_read_set_is_enough_to_decide_the_condition(
        expr in expr_strategy(),
        event in event_strategy(),
    ) {
        let bytecode = program(&expr);
        let Projection::Reads(paths) = analyze_condition(&bytecode).projection else {
            // Every shape this generator emits is projectable, so a fallback here means the
            // analysis lost precision on ordinary cohort bytecode rather than that the case is
            // uninteresting.
            prop_assert!(false, "{expr:?} was not narrowed");
            return Ok(());
        };
        let full = evaluate(&bytecode, &event.to_stream_event());
        let projected = evaluate(&bytecode, &event.projected(&paths));
        prop_assert_eq!(
            &full, &projected,
            "{:?} read {:?} but disagreed once projected",
            expr,
            paths.iter().map(ReadPath::render).collect::<Vec<_>>()
        );
    }
}

/// The harness has to be able to fail. Dropping one claimed key from the projection must make some
/// generated condition disagree; if it did not, the equivalence property above would be vacuous.
#[test]
fn dropping_a_claimed_key_makes_the_two_evaluations_disagree() {
    let expr = Expr::Compare {
        field: Field::Property("plan".to_owned()),
        op: CmpOp::Eq,
        literal: "alpha".to_owned(),
    };
    let bytecode = program(&expr);
    let Projection::Reads(paths) = analyze_condition(&bytecode).projection else {
        panic!("a single property comparison must narrow");
    };
    assert_eq!(
        paths.iter().map(ReadPath::render).collect::<Vec<_>>(),
        ["properties.plan"]
    );

    let event = TestEvent {
        event: "purchase".to_owned(),
        distinct_id: "d-1".to_owned(),
        timestamp: "2026-05-26 12:34:56.789000".to_owned(),
        elements_chain: String::new(),
        properties: BTreeMap::from([("plan".to_owned(), "alpha".to_owned())]),
        person_properties: BTreeMap::new(),
    };
    assert_eq!(
        evaluate(&bytecode, &event.to_stream_event()),
        "matched:true"
    );
    assert_eq!(
        evaluate(&bytecode, &event.projected(&paths)),
        "matched:true"
    );
    assert_eq!(
        evaluate(&bytecode, &event.projected(&BTreeSet::new())),
        "matched:false",
        "projecting nothing still matched, so the comparison never depended on the key"
    );
}

/// The emitter must produce what the compiler produces. This pins the one program whose real
/// compiled form is known from the catalog loader's own fixtures, so a change to the emitter that
/// drifted from the compiler would be caught here rather than silently weakening every case above.
#[test]
fn the_emitter_matches_the_compilers_output_for_an_event_equality() {
    let expr = Expr::Compare {
        field: Field::Event,
        op: CmpOp::Eq,
        literal: "purchase".to_owned(),
    };
    assert_eq!(
        program(&expr),
        vec![
            json!("_H"),
            json!(1),
            json!(32),
            json!("purchase"),
            json!(32),
            json!("event"),
            json!(1),
            json!(1),
            json!(11),
            json!(38),
        ]
    );
}

/// A nested path must be pushed leaf first, so `GET_GLOBAL` pops `properties` before `plan`. The
/// reversed reading would record `plan.properties` and project a column that does not exist.
#[test]
fn a_nested_path_is_emitted_leaf_first_and_read_root_first() {
    let expr = Expr::Compare {
        field: Field::Property("plan".to_owned()),
        op: CmpOp::Eq,
        literal: "alpha".to_owned(),
    };
    let bytecode = program(&expr);
    assert_eq!(
        &bytecode[4..10],
        &[
            json!(32),
            json!("plan"),
            json!(32),
            json!("properties"),
            json!(1),
            json!(2),
        ]
    );
    let Projection::Reads(paths) = analyze_condition(&bytecode).projection else {
        panic!("a single property comparison must narrow");
    };
    assert_eq!(
        paths.iter().map(ReadPath::render).collect::<Vec<_>>(),
        ["properties.plan"]
    );
}
