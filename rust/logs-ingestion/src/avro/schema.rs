//! Avro schemas, read from a container header and written back as avsc writes them.

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, LazyLock, Mutex, OnceLock};

use super::AvroError;
use crate::js::{json_parse, json_stringify, JsObject, JsString, JsValue};

#[derive(Debug, Clone, PartialEq)]
pub enum Schema {
    Null,
    Boolean,
    Int,
    Long,
    Float,
    Double,
    Bytes,
    String,
    Record(Arc<RecordSchema>),
    Enum(Arc<EnumSchema>),
    Fixed(Arc<FixedSchema>),
    Array(Box<Schema>),
    Map(Box<Schema>),
    /// avsc's default unwrapped union: the value carries its own branch.
    Union(Vec<Schema>),
}

#[derive(Debug, Clone, PartialEq)]
pub struct RecordSchema {
    pub name: String,
    pub fields: Vec<Field>,
    pub aliases: Vec<String>,
    pub doc: Option<String>,
    pub field_index: HashMap<Arc<str>, usize>,
    pub(crate) avsc_json: AvscJsonMemo,
}

/// Computed once. It takes no part in equality.
#[derive(Debug, Clone, Default)]
pub(crate) struct AvscJsonMemo(OnceLock<String>);

impl PartialEq for AvscJsonMemo {
    fn eq(&self, _: &Self) -> bool {
        true
    }
}

/// Producers send the same few schemas, so parsed schemas are kept by their exact text.
const SCHEMA_CACHE_CAPACITY: usize = 64;

static SCHEMA_CACHE: LazyLock<Mutex<HashMap<String, Schema, ahash::RandomState>>> =
    LazyLock::new(Default::default);

#[derive(Debug, Clone, PartialEq)]
pub struct Field {
    pub name: Arc<str>,
    pub schema: Schema,
    pub default: Option<JsValue>,
    pub order: Option<String>,
    pub aliases: Vec<String>,
    pub doc: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct EnumSchema {
    pub name: String,
    pub symbols: Vec<String>,
    pub default: Option<String>,
    pub aliases: Vec<String>,
    pub doc: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct FixedSchema {
    pub name: String,
    pub size: usize,
    pub aliases: Vec<String>,
}

fn schema_error(message: impl Into<String>) -> AvroError {
    AvroError::Schema(message.into())
}

fn get_str<'a>(object: &'a JsObject, key: &str) -> Option<&'a str> {
    object
        .get(key)
        .and_then(|v| v.as_js_string())
        .and_then(JsString::as_str)
}

fn get_strings(object: &JsObject, key: &str) -> Vec<String> {
    match object.get(key) {
        Some(JsValue::Array(items)) => items
            .iter()
            .filter_map(|v| v.as_js_string().map(|s| s.to_string()))
            .collect(),
        _ => Vec::new(),
    }
}

struct Parser {
    named: HashMap<String, Schema>,
}

fn qualify(name: &str, namespace: Option<&str>) -> String {
    if name.contains('.') {
        return name.to_string();
    }
    match namespace {
        Some(ns) if !ns.is_empty() => format!("{ns}.{name}"),
        _ => name.to_string(),
    }
}

impl Parser {
    fn parse(&mut self, value: &JsValue, namespace: Option<&str>) -> Result<Schema, AvroError> {
        match value {
            JsValue::String(name) => self.parse_name(&name.to_string(), namespace),
            JsValue::Array(branches) => Ok(Schema::Union(
                branches
                    .iter()
                    .map(|b| self.parse(b, namespace))
                    .collect::<Result<_, _>>()?,
            )),
            JsValue::Object(object) => self.parse_object(object, namespace),
            _ => Err(schema_error("invalid schema")),
        }
    }

    fn parse_name(&mut self, name: &str, namespace: Option<&str>) -> Result<Schema, AvroError> {
        Ok(match name {
            "null" => Schema::Null,
            "boolean" => Schema::Boolean,
            "int" => Schema::Int,
            "long" => Schema::Long,
            "float" => Schema::Float,
            "double" => Schema::Double,
            "bytes" => Schema::Bytes,
            "string" => Schema::String,
            other => self
                .named
                .get(&qualify(other, namespace))
                .or_else(|| self.named.get(other))
                .cloned()
                .ok_or_else(|| schema_error(format!("undefined type name: {other}")))?,
        })
    }

    fn parse_object(
        &mut self,
        object: &JsObject,
        namespace: Option<&str>,
    ) -> Result<Schema, AvroError> {
        let type_name = get_str(object, "type").ok_or_else(|| schema_error("missing type"))?;
        match type_name {
            "record" | "error" => {
                let name = qualify(
                    get_str(object, "name").ok_or_else(|| schema_error("missing record name"))?,
                    get_str(object, "namespace").or(namespace),
                );
                let ns = name.rsplit_once('.').map(|(ns, _)| ns.to_string());
                let mut fields = Vec::new();
                let Some(JsValue::Array(raw_fields)) = object.get("fields") else {
                    return Err(schema_error("missing fields"));
                };
                for raw in raw_fields {
                    let JsValue::Object(f) = raw else {
                        return Err(schema_error("invalid field"));
                    };
                    let field_type = f
                        .get("type")
                        .ok_or_else(|| schema_error("missing field type"))?;
                    fields.push(Field {
                        name: Arc::from(
                            get_str(f, "name").ok_or_else(|| schema_error("missing field name"))?,
                        ),
                        schema: self.parse(field_type, ns.as_deref())?,
                        default: f.get("default").cloned(),
                        order: get_str(f, "order")
                            .filter(|o| *o != "ascending")
                            .map(str::to_string),
                        aliases: get_strings(f, "aliases"),
                        doc: get_str(f, "doc").map(str::to_string),
                    });
                }
                let field_index = fields
                    .iter()
                    .enumerate()
                    .map(|(i, f)| (f.name.clone(), i))
                    .collect();
                let schema = Schema::Record(Arc::new(RecordSchema {
                    name: name.clone(),
                    fields,
                    aliases: get_strings(object, "aliases"),
                    doc: get_str(object, "doc").map(str::to_string),
                    field_index,
                    avsc_json: AvscJsonMemo::default(),
                }));
                self.named.insert(name, schema.clone());
                Ok(schema)
            }
            "enum" => {
                let name = qualify(
                    get_str(object, "name").ok_or_else(|| schema_error("missing enum name"))?,
                    get_str(object, "namespace").or(namespace),
                );
                let schema = Schema::Enum(Arc::new(EnumSchema {
                    name: name.clone(),
                    symbols: get_strings(object, "symbols"),
                    default: get_str(object, "default").map(str::to_string),
                    aliases: get_strings(object, "aliases"),
                    doc: get_str(object, "doc").map(str::to_string),
                }));
                self.named.insert(name, schema.clone());
                Ok(schema)
            }
            "fixed" => {
                let name = qualify(
                    get_str(object, "name").ok_or_else(|| schema_error("missing fixed name"))?,
                    get_str(object, "namespace").or(namespace),
                );
                let size = match object.get("size") {
                    Some(JsValue::Number(n)) if *n >= 0.0 => *n as usize,
                    _ => return Err(schema_error("invalid fixed size")),
                };
                let schema = Schema::Fixed(Arc::new(FixedSchema {
                    name: name.clone(),
                    size,
                    aliases: get_strings(object, "aliases"),
                }));
                self.named.insert(name, schema.clone());
                Ok(schema)
            }
            "array" => Ok(Schema::Array(Box::new(
                self.parse(
                    object
                        .get("items")
                        .ok_or_else(|| schema_error("missing items"))?,
                    namespace,
                )?,
            ))),
            "map" => Ok(Schema::Map(Box::new(
                self.parse(
                    object
                        .get("values")
                        .ok_or_else(|| schema_error("missing values"))?,
                    namespace,
                )?,
            ))),
            // avsc reads a primitive written as an object as the plain primitive and drops an unregistered logical type.
            primitive => self.parse_name(primitive, namespace),
        }
    }
}

impl Schema {
    pub fn parse_json(text: &str) -> Result<Schema, AvroError> {
        let value = json_parse(text).map_err(|e| schema_error(e.to_string()))?;
        Parser {
            named: HashMap::new(),
        }
        .parse(&value, None)
    }

    /// A parse is a pure function of the text, so a cached schema is the same value. Errors are not cached.
    pub fn parse_json_cached(text: &str) -> Result<Schema, AvroError> {
        if let Some(schema) = SCHEMA_CACHE.lock().unwrap().get(text) {
            return Ok(schema.clone());
        }
        let schema = Schema::parse_json(text)?;
        let mut cache = SCHEMA_CACHE.lock().unwrap();
        if cache.len() >= SCHEMA_CACHE_CAPACITY {
            cache.clear();
        }
        cache.insert(text.to_string(), schema.clone());
        Ok(schema)
    }

    /// As avsc's `getSchema({ exportAttrs: true })`: it drops unregistered logical types and custom attributes, and names a type after its first definition.
    pub fn to_avsc_json(&self) -> String {
        self.avsc_json_str().to_string()
    }

    pub(crate) fn avsc_json_str(&self) -> std::borrow::Cow<'_, str> {
        match self {
            Schema::Record(record) => std::borrow::Cow::Borrowed(
                record
                    .avsc_json
                    .0
                    .get_or_init(|| json_stringify(&self.export(&mut HashSet::new()))),
            ),
            _ => std::borrow::Cow::Owned(json_stringify(&self.export(&mut HashSet::new()))),
        }
    }

    fn export(&self, seen: &mut HashSet<String>) -> JsValue {
        let s = |v: &str| JsValue::string(v);
        let strings = |items: &[String]| JsValue::Array(items.iter().map(|i| s(i)).collect());
        match self {
            Schema::Null => s("null"),
            Schema::Boolean => s("boolean"),
            Schema::Int => s("int"),
            Schema::Long => s("long"),
            Schema::Float => s("float"),
            Schema::Double => s("double"),
            Schema::Bytes => s("bytes"),
            Schema::String => s("string"),
            Schema::Union(branches) => {
                JsValue::Array(branches.iter().map(|b| b.export(seen)).collect())
            }
            Schema::Array(items) => {
                let mut o = JsObject::new();
                o.insert_str("type", s("array"));
                o.insert_str("items", items.export(seen));
                JsValue::Object(o)
            }
            Schema::Map(values) => {
                let mut o = JsObject::new();
                o.insert_str("type", s("map"));
                o.insert_str("values", values.export(seen));
                JsValue::Object(o)
            }
            Schema::Record(record) => {
                if !seen.insert(record.name.clone()) {
                    return s(&record.name);
                }
                let mut o = JsObject::new();
                o.insert_str("name", s(&record.name));
                o.insert_str("type", s("record"));
                let fields = record
                    .fields
                    .iter()
                    .map(|f| {
                        let mut fo = JsObject::new();
                        fo.insert_str("name", s(&f.name));
                        fo.insert_str("type", f.schema.export(seen));
                        if let Some(default) = &f.default {
                            fo.insert_str("default", default.clone());
                        }
                        if let Some(order) = &f.order {
                            fo.insert_str("order", s(order));
                        }
                        if !f.aliases.is_empty() {
                            fo.insert_str("aliases", strings(&f.aliases));
                        }
                        if let Some(doc) = &f.doc {
                            fo.insert_str("doc", s(doc));
                        }
                        JsValue::Object(fo)
                    })
                    .collect();
                o.insert_str("fields", JsValue::Array(fields));
                if !record.aliases.is_empty() {
                    o.insert_str("aliases", strings(&record.aliases));
                }
                if let Some(doc) = &record.doc {
                    o.insert_str("doc", s(doc));
                }
                JsValue::Object(o)
            }
            Schema::Enum(e) => {
                if !seen.insert(e.name.clone()) {
                    return s(&e.name);
                }
                let mut o = JsObject::new();
                o.insert_str("name", s(&e.name));
                o.insert_str("type", s("enum"));
                o.insert_str("symbols", strings(&e.symbols));
                if let Some(default) = &e.default {
                    o.insert_str("default", s(default));
                }
                if !e.aliases.is_empty() {
                    o.insert_str("aliases", strings(&e.aliases));
                }
                if let Some(doc) = &e.doc {
                    o.insert_str("doc", s(doc));
                }
                JsValue::Object(o)
            }
            Schema::Fixed(f) => {
                if !seen.insert(f.name.clone()) {
                    return s(&f.name);
                }
                let mut o = JsObject::new();
                o.insert_str("name", s(&f.name));
                o.insert_str("type", s("fixed"));
                o.insert_str("size", JsValue::Number(f.size as f64));
                if !f.aliases.is_empty() {
                    o.insert_str("aliases", strings(&f.aliases));
                }
                JsValue::Object(o)
            }
        }
    }

    /// The schema as avsc prints it in an "invalid value" error, for primitives.
    pub(crate) fn short_name(&self) -> String {
        match self {
            Schema::Record(r) => r.name.clone(),
            Schema::Enum(e) => e.name.clone(),
            Schema::Fixed(f) => f.name.clone(),
            other => {
                let exported = other.export(&mut HashSet::new());
                json_stringify(&exported)
            }
        }
    }
}
