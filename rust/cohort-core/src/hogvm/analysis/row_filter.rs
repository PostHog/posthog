//! Derives the event property values a row must carry for a condition's program to return true.
//!
//! A filter that drops a row the program matches loses membership, so the grammar is exact: string
//! literals, reads of `event` and `properties.<key>`, `==`, `AND` and `OR`. Any other opcode yields
//! no filter. An unrecognized `==` may still stand as an `AND` operand and is ignored, because the
//! VM's `AND` evaluates every operand and requires all of them to be truthy.

use std::collections::{BTreeMap, BTreeSet};
use std::str::FromStr;
use std::sync::Arc;

use hogvm::{Num, Operation};
use serde_json::Value;

use super::decode::{decode, InstrKind};
use super::exactness::{ColumnExactness, Exactness};
use super::projection::ELEMENTS_CHAIN_PROPERTY;

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EventEqualities {
    pub row_filter: Option<EventRowFilter>,
    /// `None` when the program reads the whole object or the grammar does not parse it.
    pub column_exactness: Option<ColumnExactness>,
}

/// A necessary condition for the program to return true: the row's `event` is [`Self::event`], and
/// every conjunct has some `(key, value)` with `properties[key] == value` under HogVM equality.
///
/// HogVM equality coerces, so besides the string `value` it also holds for any JSON boolean
/// (compared with `value.to_lowercase() == "true"`) and for an object carrying a temporal marker
/// (compared by epoch). A value that parses as a number is never kept, because it would also equal a
/// JSON number. A consumer that renders a row filter must admit all of these.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EventRowFilter {
    pub event: String,
    /// Never empty.
    pub conjuncts: Vec<PropertyAlternatives>,
}

/// A disjunction of `properties[key] == value`, grouped by key.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PropertyAlternatives(BTreeMap<String, BTreeSet<String>>);

impl PropertyAlternatives {
    pub fn iter(&self) -> impl Iterator<Item = (&str, &BTreeSet<String>)> {
        self.0.iter().map(|(key, values)| (key.as_str(), values))
    }
}

#[derive(Debug, Clone)]
enum Node {
    Literal(Arc<str>),
    /// A `GET_GLOBAL` chain, root first.
    Global(Vec<Arc<str>>),
    EventIs(Arc<str>),
    PropertyIs {
        key: Arc<str>,
        value: Arc<str>,
    },
    /// Any other `==`, kept for the `properties` reads in its operands.
    OtherEquality(Box<Node>, Box<Node>),
    And(Vec<Node>),
    Or(Vec<Node>),
}

enum PropertyRead<'a> {
    Compared {
        key: &'a str,
        literal: &'a str,
    },
    /// Any other read of the key, including a path under it.
    Other {
        key: &'a str,
    },
    WholeObject,
}

impl<'a> PropertyRead<'a> {
    fn exactness(self) -> Option<(&'a str, Exactness)> {
        match self {
            Self::Compared { key, literal } => Some((key, Exactness::of_literal(literal))),
            Self::Other { key } => Some((key, Exactness::Inexact)),
            Self::WholeObject => None,
        }
    }

    fn of_chain(chain: &'a [Arc<str>]) -> Option<Self> {
        match chain {
            [root] if &**root == "properties" => Some(Self::WholeObject),
            [root, key, ..] if &**root == "properties" => Some(Self::Other { key }),
            // `elements_chain` falls back to this property.
            [root, ..] if &**root == "elements_chain" => Some(Self::Other {
                key: ELEMENTS_CHAIN_PROPERTY,
            }),
            _ => None,
        }
    }
}

impl Node {
    const fn is_boolean(&self) -> bool {
        !matches!(self, Self::Literal(_) | Self::Global(_))
    }

    fn property_reads(&self) -> PropertyReads<'_> {
        PropertyReads {
            pending: vec![self],
        }
    }
}

struct PropertyReads<'a> {
    pending: Vec<&'a Node>,
}

impl<'a> Iterator for PropertyReads<'a> {
    type Item = PropertyRead<'a>;

    fn next(&mut self) -> Option<Self::Item> {
        while let Some(node) = self.pending.pop() {
            match node {
                Node::Literal(_) | Node::EventIs(_) => {}
                Node::Global(chain) => {
                    if let Some(read) = PropertyRead::of_chain(chain) {
                        return Some(read);
                    }
                }
                Node::PropertyIs { key, value } => {
                    return Some(PropertyRead::Compared {
                        key,
                        literal: value,
                    })
                }
                Node::OtherEquality(left, right) => self.pending.extend([&**left, &**right]),
                Node::And(operands) | Node::Or(operands) => self.pending.extend(operands),
            }
        }
        None
    }
}

pub fn event_equalities(bytecode: &[Value]) -> EventEqualities {
    let Some(root) = parse(bytecode) else {
        return EventEqualities::default();
    };
    EventEqualities {
        // A literal comparison keeps its answer under any `==`, `AND` or `OR` above it.
        column_exactness: root.property_reads().map(PropertyRead::exactness).collect(),
        row_filter: row_filter(root),
    }
}

fn row_filter(root: Node) -> Option<EventRowFilter> {
    let mut conjuncts = Vec::new();
    flatten_and(root, &mut conjuncts);

    let mut event: Option<Arc<str>> = None;
    let mut filters = Vec::new();
    for conjunct in conjuncts {
        match conjunct {
            Node::EventIs(name) => match &event {
                Some(existing) if *existing != name => return None,
                Some(_) => {}
                None => event = Some(name),
            },
            other => filters.extend(alternatives(other)),
        }
    }
    let event = event?;
    if filters.is_empty() {
        return None;
    }
    Some(EventRowFilter {
        event: event.to_string(),
        conjuncts: filters,
    })
}

fn parse(bytecode: &[Value]) -> Option<Node> {
    let decoded = decode(bytecode).ok()?;
    let mut stack: Vec<Node> = Vec::new();
    let mut returned: Option<Node> = None;
    for instr in &decoded.instrs {
        // The loader appends a `RETURN` to programs that may already end in one.
        if returned.is_some() {
            if matches!(instr.kind, InstrKind::Bare(Operation::Return)) {
                continue;
            }
            return None;
        }
        match &instr.kind {
            InstrKind::String(literal) => stack.push(Node::Literal(literal.clone())),
            InstrKind::Counted(Operation::GetGlobal, count) => {
                if *count == 0 {
                    return None;
                }
                let mut chain = Vec::with_capacity(*count);
                for _ in 0..*count {
                    match stack.pop()? {
                        Node::Literal(segment) => chain.push(segment),
                        _ => return None,
                    }
                }
                stack.push(Node::Global(chain));
            }
            InstrKind::Bare(Operation::Eq) => {
                let top = stack.pop()?;
                let below = stack.pop()?;
                stack.push(equality(top, below));
            }
            InstrKind::Counted(op @ (Operation::And | Operation::Or), count) => {
                if *count == 0 || *count > stack.len() {
                    return None;
                }
                let operands = stack.split_off(stack.len() - count);
                if !operands.iter().all(Node::is_boolean) {
                    return None;
                }
                stack.push(if *op == Operation::And {
                    Node::And(operands)
                } else {
                    Node::Or(operands)
                });
            }
            InstrKind::Bare(Operation::Return) => {
                if stack.len() != 1 {
                    return None;
                }
                returned = stack.pop();
            }
            _ => return None,
        }
    }
    returned.filter(Node::is_boolean)
}

fn equality(left: Node, right: Node) -> Node {
    let recognized = match (&left, &right) {
        (Node::Literal(literal), Node::Global(chain))
        | (Node::Global(chain), Node::Literal(literal)) => match chain.as_slice() {
            [root] if &**root == "event" => Some(Node::EventIs(literal.clone())),
            [root, key] if &**root == "properties" => Some(Node::PropertyIs {
                key: key.clone(),
                value: literal.clone(),
            }),
            _ => None,
        },
        _ => None,
    };
    recognized.unwrap_or_else(|| Node::OtherEquality(Box::new(left), Box::new(right)))
}

fn flatten_and(node: Node, out: &mut Vec<Node>) {
    match node {
        Node::And(operands) => {
            for operand in operands {
                flatten_and(operand, out);
            }
        }
        other => out.push(other),
    }
}

fn flatten_or(node: Node, out: &mut Vec<Node>) {
    match node {
        Node::Or(operands) => {
            for operand in operands {
                flatten_or(operand, out);
            }
        }
        other => out.push(other),
    }
}

fn alternatives(conjunct: Node) -> Option<PropertyAlternatives> {
    let mut disjuncts = Vec::new();
    flatten_or(conjunct, &mut disjuncts);
    let mut by_key: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for disjunct in disjuncts {
        let Node::PropertyIs { key, value } = disjunct else {
            return None;
        };
        if Num::from_str(&value).is_ok() {
            return None;
        }
        by_key
            .entry(key.to_string())
            .or_default()
            .insert(value.to_string());
    }
    (!by_key.is_empty()).then_some(PropertyAlternatives(by_key))
}

#[cfg(test)]
mod tests {
    use proptest::prelude::*;
    use serde_json::json;

    use super::*;
    use crate::hogvm::{evaluate_detailed, EvalOutcome};

    const STRING: u64 = Operation::String as u64;
    const GET_GLOBAL: u64 = Operation::GetGlobal as u64;
    const EQ: u64 = Operation::Eq as u64;
    const AND: u64 = Operation::And as u64;
    const OR: u64 = Operation::Or as u64;
    const RETURN: u64 = Operation::Return as u64;

    fn event_is(name: &str) -> Vec<Value> {
        vec![
            json!(STRING),
            json!(name),
            json!(STRING),
            json!("event"),
            json!(GET_GLOBAL),
            json!(1),
            json!(EQ),
        ]
    }

    fn property_is(key: &str, value: &str) -> Vec<Value> {
        vec![
            json!(STRING),
            json!(value),
            json!(STRING),
            json!(key),
            json!(STRING),
            json!("properties"),
            json!(GET_GLOBAL),
            json!(2),
            json!(EQ),
        ]
    }

    fn person_property_is(key: &str, value: &str) -> Vec<Value> {
        vec![
            json!(STRING),
            json!(value),
            json!(STRING),
            json!(key),
            json!(STRING),
            json!("properties"),
            json!(STRING),
            json!("person"),
            json!(GET_GLOBAL),
            json!(3),
            json!(EQ),
        ]
    }

    fn fold(op: u64, operands: Vec<Vec<Value>>) -> Vec<Value> {
        let count = operands.len();
        let mut tokens: Vec<Value> = operands.into_iter().flatten().collect();
        tokens.push(json!(op));
        tokens.push(json!(count));
        tokens
    }

    fn program(body: Vec<Value>) -> Vec<Value> {
        let mut tokens = vec![json!("_H"), json!(1)];
        tokens.extend(body);
        tokens.push(json!(RETURN));
        tokens
    }

    fn filter(event: &str, conjuncts: &[&[(&str, &[&str])]]) -> EventRowFilter {
        EventRowFilter {
            event: event.to_owned(),
            conjuncts: conjuncts
                .iter()
                .map(|alternatives| {
                    PropertyAlternatives(
                        alternatives
                            .iter()
                            .map(|(key, values)| {
                                (
                                    (*key).to_owned(),
                                    values.iter().map(|value| (*value).to_owned()).collect(),
                                )
                            })
                            .collect(),
                    )
                })
                .collect(),
        }
    }

    #[test]
    fn compiled_event_filters_yield_their_row_filters() {
        let cases: Vec<(&str, Vec<Value>, EventRowFilter)> = vec![
            (
                "one exact value",
                fold(
                    AND,
                    vec![
                        event_is("$feature_flag_called"),
                        property_is("$feature_flag", "my-flag"),
                    ],
                ),
                filter(
                    "$feature_flag_called",
                    &[&[("$feature_flag", &["my-flag"])]],
                ),
            ),
            (
                "a value list",
                fold(
                    AND,
                    vec![
                        event_is("$feature_flag_called"),
                        fold(
                            OR,
                            vec![
                                property_is("$feature_flag", "a"),
                                property_is("$feature_flag", "b"),
                            ],
                        ),
                    ],
                ),
                filter("$feature_flag_called", &[&[("$feature_flag", &["a", "b"])]]),
            ),
            (
                "two filters, one of them on the person",
                fold(
                    AND,
                    vec![
                        event_is("purchase"),
                        fold(
                            AND,
                            vec![
                                person_property_is("plan", "pro"),
                                property_is("currency", "EUR"),
                            ],
                        ),
                    ],
                ),
                filter("purchase", &[&[("currency", &["EUR"])]]),
            ),
            (
                "two event properties",
                fold(
                    AND,
                    vec![
                        event_is("purchase"),
                        fold(
                            AND,
                            vec![property_is("currency", "EUR"), property_is("plan", "pro")],
                        ),
                    ],
                ),
                filter(
                    "purchase",
                    &[&[("currency", &["EUR"])], &[("plan", &["pro"])]],
                ),
            ),
            (
                "a disjunction across keys",
                fold(
                    AND,
                    vec![
                        event_is("purchase"),
                        fold(OR, vec![property_is("a", "x"), property_is("b", "y")]),
                    ],
                ),
                filter("purchase", &[&[("a", &["x"]), ("b", &["y"])]]),
            ),
        ];
        for (label, body, expected) in cases {
            assert_eq!(
                event_equalities(&program(body)).row_filter,
                Some(expected),
                "{label}"
            );
        }
    }

    #[test]
    fn programs_outside_the_grammar_yield_no_filter() {
        let not_equal = {
            let mut tokens = property_is("$feature_flag", "my-flag");
            *tokens.last_mut().unwrap() = json!(Operation::NotEq as u64);
            fold(AND, vec![event_is("e"), tokens])
        };
        let case_insensitive = {
            let mut tokens = property_is("$current_url", "%pricing%");
            *tokens.last_mut().unwrap() = json!(Operation::Ilike as u64);
            fold(AND, vec![event_is("e"), tokens])
        };
        let cases: Vec<(&str, Vec<Value>)> = vec![
            ("the event alone", event_is("e")),
            ("a property alone", property_is("k", "v")),
            ("a negated equality", not_equal),
            ("a pattern match", case_insensitive),
            (
                "a numeric value",
                fold(AND, vec![event_is("e"), property_is("k", "42")]),
            ),
            (
                "a value that parses as a float",
                fold(AND, vec![event_is("e"), property_is("k", "1e3")]),
            ),
            (
                "only a nested property path",
                fold(
                    AND,
                    vec![
                        event_is("e"),
                        vec![
                            json!(STRING),
                            json!("v"),
                            json!(STRING),
                            json!("b"),
                            json!(STRING),
                            json!("a"),
                            json!(STRING),
                            json!("properties"),
                            json!(GET_GLOBAL),
                            json!(3),
                            json!(EQ),
                        ],
                    ],
                ),
            ),
            (
                "an OR that also admits the event itself",
                fold(
                    AND,
                    vec![
                        event_is("e"),
                        fold(OR, vec![property_is("k", "v"), event_is("f")]),
                    ],
                ),
            ),
            (
                "the event under an OR",
                fold(OR, vec![event_is("e"), property_is("k", "v")]),
            ),
            (
                "two different events",
                fold(
                    AND,
                    vec![event_is("e"), event_is("f"), property_is("k", "v")],
                ),
            ),
            (
                "a string operand of AND",
                fold(AND, vec![event_is("e"), vec![json!(STRING), json!("v")]]),
            ),
        ];
        for (label, body) in cases {
            assert_eq!(event_equalities(&program(body)).row_filter, None, "{label}");
        }

        let mut unterminated = program(fold(AND, vec![event_is("e"), property_is("k", "v")]));
        unterminated.pop();
        assert_eq!(
            event_equalities(&unterminated),
            EventEqualities::default(),
            "no RETURN"
        );
        let mut trailing = program(fold(AND, vec![event_is("e"), property_is("k", "v")]));
        trailing.push(json!(Operation::True as u64));
        assert_eq!(
            event_equalities(&trailing),
            EventEqualities::default(),
            "code after RETURN"
        );
    }

    fn exact_keys(body: Vec<Value>) -> BTreeSet<String> {
        event_equalities(&program(body))
            .column_exactness
            .map(|keys| keys.exact_keys().map(str::to_owned).collect())
            .unwrap_or_default()
    }

    #[test]
    fn a_key_is_column_exact_only_when_every_read_compares_it_with_an_exact_literal() {
        let under_the_key = vec![
            json!(STRING),
            json!("v"),
            json!(STRING),
            json!("sub"),
            json!(STRING),
            json!("k"),
            json!(STRING),
            json!("properties"),
            json!(GET_GLOBAL),
            json!(3),
            json!(EQ),
        ];
        let against_the_event = vec![
            json!(STRING),
            json!("k"),
            json!(STRING),
            json!("properties"),
            json!(GET_GLOBAL),
            json!(2),
            json!(STRING),
            json!("event"),
            json!(GET_GLOBAL),
            json!(1),
            json!(EQ),
        ];
        let the_elements_chain = vec![
            json!(STRING),
            json!("x"),
            json!(STRING),
            json!("elements_chain"),
            json!(GET_GLOBAL),
            json!(1),
            json!(EQ),
        ];
        let the_whole_object = vec![
            json!(STRING),
            json!("v"),
            json!(STRING),
            json!("properties"),
            json!(GET_GLOBAL),
            json!(1),
            json!(EQ),
        ];
        let pattern = {
            let mut tokens = property_is("k", "%v%");
            *tokens.last_mut().unwrap() = json!(Operation::Ilike as u64);
            tokens
        };
        let cases: Vec<(&str, Vec<Value>, &[&str])> = vec![
            (
                "one exact literal",
                fold(
                    AND,
                    vec![event_is("e"), property_is("k", "https://example.com/")],
                ),
                &["k"],
            ),
            (
                "a value list",
                fold(
                    AND,
                    vec![
                        event_is("e"),
                        fold(OR, vec![property_is("k", "a"), property_is("k", "b")]),
                    ],
                ),
                &["k"],
            ),
            (
                "an inexact literal beside an exact one",
                fold(
                    AND,
                    vec![
                        event_is("e"),
                        fold(OR, vec![property_is("k", "a"), property_is("k", "TRUE")]),
                        property_is("j", "b"),
                    ],
                ),
                &["j"],
            ),
            (
                "a path under the key",
                fold(
                    AND,
                    vec![
                        event_is("e"),
                        property_is("k", "v"),
                        under_the_key,
                        property_is("j", "b"),
                    ],
                ),
                &["j"],
            ),
            (
                "the key compared with another global",
                fold(
                    AND,
                    vec![
                        event_is("e"),
                        property_is("k", "v"),
                        against_the_event,
                        property_is("j", "b"),
                    ],
                ),
                &["j"],
            ),
            (
                "an OR with a person property, which no row filter covers",
                fold(
                    AND,
                    vec![
                        event_is("e"),
                        fold(
                            OR,
                            vec![property_is("k", "v"), person_property_is("plan", "pro")],
                        ),
                    ],
                ),
                &["k"],
            ),
            (
                "the elements chain, which falls back to its property",
                fold(
                    AND,
                    vec![
                        event_is("e"),
                        property_is("$elements_chain", "a"),
                        the_elements_chain,
                        property_is("j", "b"),
                    ],
                ),
                &["j"],
            ),
            (
                "the whole object",
                fold(
                    AND,
                    vec![event_is("e"), property_is("j", "b"), the_whole_object],
                ),
                &[],
            ),
            (
                "a program outside the grammar",
                fold(AND, vec![event_is("e"), property_is("j", "b"), pattern]),
                &[],
            ),
        ];
        for (label, body, expected) in cases {
            let expected: BTreeSet<String> = expected.iter().map(|key| (*key).to_owned()).collect();
            assert_eq!(exact_keys(body), expected, "{label}");
        }

        for literal in [
            "", "5", "-1", "1e3", "inf", "true", "TRUE", "False", "null", "{}", "[1]", "\"q\"",
            " 5",
        ] {
            let body = fold(AND, vec![event_is("e"), property_is("k", literal)]);
            assert_eq!(exact_keys(body), BTreeSet::new(), "{literal:?}");
        }
    }

    /// Mirrors `replaceRegexpAll(JSONExtractRaw(properties, key), '^"|"$', '')`.
    fn trim_quotes(raw: &str) -> &str {
        let raw = raw.strip_prefix('"').unwrap_or(raw);
        raw.strip_suffix('"').unwrap_or(raw)
    }

    /// Mirrors `if(isValidJSON(m), m, concat('"', m, '"'))`.
    fn rebuild(column: &str) -> Value {
        serde_json::from_str(column).unwrap_or_else(|_| {
            serde_json::from_str(&format!("\"{column}\""))
                .expect("a string's escaped body is a valid string once quoted again")
        })
    }

    fn exact_literal() -> impl Strategy<Value = String> {
        prop_oneof![
            Just("my-flag".to_owned()),
            Just("https://example.com/p?q=1".to_owned()),
            Just("2024-01-01".to_owned()),
            Just("a\"b\\c\n".to_owned()),
            Just("é😀".to_owned()),
            // Exact, but close to retyped text.
            Just("True ".to_owned()),
            Just("5a".to_owned()),
            Just("nul".to_owned()),
            Just("[".to_owned()),
            "\\PC{1,6}",
        ]
        .prop_filter("a literal a column decides exactly", |literal| {
            Exactness::of_literal(literal) == Exactness::Exact
        })
    }

    fn property_value() -> impl Strategy<Value = Value> {
        let leaf = prop_oneof![
            Just(Value::Null),
            any::<bool>().prop_map(Value::Bool),
            any::<i64>().prop_map(|number| json!(number)),
            (-1e6f64..1e6).prop_map(|number| json!(number)),
            prop_oneof![
                Just("my-flag".to_owned()),
                Just("true".to_owned()),
                Just("TRUE".to_owned()),
                Just("false".to_owned()),
                Just(String::new()),
                Just("2024-01-01".to_owned()),
                Just("a\"b\\c\n".to_owned()),
                // Retyped by a trim-quotes column.
                Just("5".to_owned()),
                Just("5.0".to_owned()),
                Just("null".to_owned()),
                Just("[1]".to_owned()),
                Just("{}".to_owned()),
                Just(" 5".to_owned()),
                "\\PC{0,6}",
            ]
            .prop_map(Value::String),
        ];
        leaf.prop_recursive(2, 6, 3, |inner| {
            prop_oneof![
                prop::collection::vec(inner.clone(), 0..3).prop_map(Value::Array),
                Just(json!({"__hogDateTime__": true, "dt": 1_704_067_200.0, "zone": "UTC"})),
                Just(json!({"__hogDate__": true, "year": 2024, "month": 1, "day": 1})),
                inner.prop_map(|value| json!({ "nested": value })),
            ]
        })
    }

    fn filter_value() -> impl Strategy<Value = String> {
        prop_oneof![
            Just("my-flag".to_owned()),
            Just("true".to_owned()),
            Just("True".to_owned()),
            Just("false".to_owned()),
            Just(String::new()),
            Just("2024-01-01".to_owned()),
            Just("2024-01-01T00:00:00Z".to_owned()),
            Just("a\"b\\c\n".to_owned()),
            "\\PC{0,6}",
        ]
    }

    proptest! {
        /// Checks the [`EventRowFilter`] contract against the VM, so a change to HogVM equality that
        /// matches a string against another JSON type fails here.
        #[test]
        fn a_program_match_implies_a_value_the_filter_admits(
            actual in property_value(),
            expected in filter_value(),
        ) {
            let bytecode = program(fold(
                AND,
                vec![event_is("e"), property_is("k", &expected)],
            ));
            let Some(row_filter) = event_equalities(&bytecode).row_filter else {
                prop_assert!(Num::from_str(&expected).is_ok());
                return Ok(());
            };
            prop_assert_eq!(&row_filter.event, "e");
            let globals = json!({"event": "e", "properties": {"k": actual.clone()}});
            if let EvalOutcome::Matched(true) = evaluate_detailed(&bytecode, globals) {
                let admitted = match &actual {
                    Value::String(value) => *value == expected,
                    Value::Bool(_) | Value::Object(_) => true,
                    Value::Null | Value::Number(_) | Value::Array(_) => false,
                };
                prop_assert!(admitted, "the VM matched {actual} against {expected:?}");
            }
        }

        /// The string `"false"` is excluded: the column returns it as the boolean.
        #[test]
        fn an_exact_literal_answers_a_column_rebuilt_value_like_the_stored_one(
            actual in prop::option::of(property_value()),
            literal in exact_literal(),
        ) {
            let reads_as_false = |text: &str| {
                serde_json::from_str::<Value>(text).is_ok_and(|value| value == Value::Bool(false))
            };
            prop_assume!(!matches!(&actual, Some(Value::String(text)) if reads_as_false(text)));
            let bytecode = program(fold(AND, vec![event_is("e"), property_is("k", &literal)]));
            prop_assert_eq!(
                event_equalities(&bytecode).column_exactness.and_then(|keys| keys.get("k")),
                Some(Exactness::Exact)
            );

            let column = actual
                .as_ref()
                .map_or_else(String::new, |value| trim_quotes(&value.to_string()).to_owned());
            let stored = match &actual {
                Some(value) => json!({"event": "e", "properties": {"k": value}}),
                None => json!({"event": "e", "properties": {}}),
            };
            let rebuilt = json!({"event": "e", "properties": {"k": rebuild(&column)}});
            let verdict = |globals| match evaluate_detailed(&bytecode, globals) {
                EvalOutcome::Matched(matched) => matched,
                other => panic!("an equality program failed to evaluate: {other:?}"),
            };
            prop_assert_eq!(
                verdict(stored),
                verdict(rebuilt),
                "{:?} against {:?} through the column value {:?}",
                actual,
                literal,
                column
            );
        }
    }
}
