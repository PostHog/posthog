//! View-local data, deliberately independent of the JavaScript state checkpoint.
//!
//! A table keeps what reads need beside its rows, so reads never rescan the
//! rows' JSON and mutations cost what they change: a key map, one lowercase
//! text column per field (a single buffer searched with SIMD `memmem`), the
//! table's serialized size, and cached sort orders and groupings.
use memchr::memmem::Finder;
use serde_json::{Map, Value, json};
use std::{
    borrow::Cow,
    cell::RefCell,
    cmp::Ordering,
    collections::{BTreeMap, HashMap, HashSet},
    rc::Rc,
    sync::atomic::{AtomicU64, Ordering::Relaxed},
};

pub const MAX_BYTES: usize = 16 * 1024 * 1024;
pub const MAX_ROWS: usize = 2000;
type Groups = Rc<Vec<(Value, Vec<usize>)>>;
const MISSING: (u32, u32) = (u32::MAX, u32::MAX);
static GENERATION: AtomicU64 = AtomicU64::new(1);

/// One field's searchable text: each row's lowercase display value followed by
/// a 0 byte, so a needle without 0 bytes never matches across rows. A changed
/// row appends a new segment and blanks its old one with 0s.
#[derive(Clone, Default)]
struct Column {
    text: Vec<u8>,
    /// Per row: the segment's start and end, or `MISSING`.
    spans: Vec<(u32, u32)>,
    /// (segment start, row), ascending by start.
    owners: Vec<(u32, u32)>,
    dead: usize,
}
impl Column {
    fn write(&mut self, row: usize, value: Option<&Value>) -> (u32, u32) {
        let Some(value) = value else { return MISSING };
        let start = self.text.len();
        match value {
            Value::Null => {}
            Value::String(s) => push_lower(s, &mut self.text),
            other => push_lower(&other.to_string(), &mut self.text),
        }
        let end = self.text.len();
        self.text.push(0);
        self.owners.push((start as u32, row as u32));
        (start as u32, end as u32)
    }
    fn replace(&mut self, row: usize, value: Option<&Value>) {
        let (start, end) = self.spans[row];
        if start != u32::MAX {
            self.text[start as usize..end as usize].fill(0);
            self.dead += (end - start) as usize + 1;
        }
        self.spans[row] = self.write(row, value);
    }
    fn get(&self, row: usize) -> Option<&[u8]> {
        let (start, end) = self.spans[row];
        (start != u32::MAX).then(|| &self.text[start as usize..end as usize])
    }
    /// Marks every row whose value contains the needle. Needs a needle without 0 bytes.
    fn mark(&self, finder: &Finder, hits: &mut [bool]) {
        let mut pos = 0;
        while let Some(found) = finder.find(&self.text[pos..]) {
            let at = pos + found;
            let owner = self.owners.partition_point(|(s, _)| *s as usize <= at) - 1;
            hits[self.owners[owner].1 as usize] = true;
            pos = self
                .owners
                .get(owner + 1)
                .map_or(self.text.len(), |(s, _)| *s as usize);
        }
    }
}
fn push_lower(s: &str, out: &mut Vec<u8>) {
    if s.is_ascii() {
        let start = out.len();
        out.extend_from_slice(s.as_bytes());
        out[start..].make_ascii_lowercase();
    } else {
        out.extend_from_slice(s.to_lowercase().as_bytes());
    }
}
fn key_text(key: &Value) -> Option<String> {
    (key.is_string() || key.is_number()).then(|| key.to_string())
}
fn json_len(text: &str) -> usize {
    Value::String(text.into()).to_string().len()
}
fn rows_array(args: &mut Value) -> Result<Vec<Value>, String> {
    match args.get_mut("rows").map(Value::take) {
        Some(Value::Array(rows)) => Ok(rows),
        _ => Err("Dataset rows must be an array".into()),
    }
}
fn checked_object(row: Value) -> Result<Map<String, Value>, String> {
    let Value::Object(object) = row else {
        return Err("Dataset rows must be flat objects".into());
    };
    if object.values().any(|v| v.is_array() || v.is_object()) {
        return Err("Dataset rows must contain only scalar values".into());
    }
    Ok(object)
}
const KEY_ERROR: &str = "Dataset keys must be unique strings or numbers";

#[derive(Clone)]
pub struct Table {
    pub key: String,
    pub rows: Vec<Value>,
    /// Each row's JSON, so saving copies text instead of serializing.
    texts: Vec<Box<str>>,
    /// Changes whenever the rows do, unique across tables in the process.
    pub generation: u64,
    keys: HashMap<String, usize>,
    fields: Vec<String>,
    names: HashMap<String, usize>,
    columns: Vec<Column>,
    /// Length of `{"key":…,"rows":[…]}`.
    bytes: usize,
    groups: RefCell<HashMap<String, Groups>>,
    orders: RefCell<HashMap<String, Rc<Vec<u32>>>>,
}
impl Table {
    fn new(key: String) -> Self {
        Table {
            bytes: 18 + json_len(&key),
            key,
            rows: vec![],
            texts: vec![],
            generation: GENERATION.fetch_add(1, Relaxed),
            keys: HashMap::new(),
            fields: vec![],
            names: HashMap::new(),
            columns: vec![],
            groups: RefCell::default(),
            orders: RefCell::default(),
        }
    }
    fn from_rows(key: String, rows: Vec<Value>) -> Result<Self, String> {
        let mut table = Table::new(key);
        table.rows.reserve(rows.len());
        table.texts.reserve(rows.len());
        table.keys.reserve(rows.len());
        for row in rows {
            let object = checked_object(row)?;
            let key = key_text(object.get(&table.key).unwrap_or(&Value::Null)).ok_or(KEY_ERROR)?;
            if table.keys.contains_key(&key) {
                return Err(KEY_ERROR.into());
            }
            table.append(key, Value::Object(object));
        }
        Ok(table)
    }
    /// Adds a checked row whose key is new.
    fn append(&mut self, key: String, row: Value) {
        let i = self.rows.len();
        let object = row.as_object().expect("checked row");
        let mut known = 0;
        for (field, column) in self.fields.iter().zip(&mut self.columns) {
            let value = object.get(field);
            known += usize::from(value.is_some());
            let span = column.write(i, value);
            column.spans.push(span);
        }
        for (field, value) in object.iter().filter(|_| known < object.len()) {
            if !self.names.contains_key(field) {
                let mut column = Column {
                    spans: vec![MISSING; i],
                    ..Default::default()
                };
                let span = column.write(i, Some(value));
                column.spans.push(span);
                self.names.insert(field.clone(), self.columns.len());
                self.fields.push(field.clone());
                self.columns.push(column);
            }
        }
        let text = row.to_string().into_boxed_str();
        self.bytes += text.len() + usize::from(i > 0);
        self.texts.push(text);
        self.keys.insert(key, i);
        self.rows.push(row);
    }
    /// Replaces a row in place with a checked row that has the same key.
    fn update(&mut self, i: usize, row: Value) {
        let object = row.as_object().expect("checked row");
        for (field, column) in self.fields.iter().zip(&mut self.columns) {
            column.replace(i, object.get(field));
        }
        for (field, value) in object {
            if !self.names.contains_key(field) {
                let mut column = Column {
                    spans: vec![MISSING; self.rows.len()],
                    ..Default::default()
                };
                column.replace(i, Some(value));
                self.names.insert(field.clone(), self.columns.len());
                self.fields.push(field.clone());
                self.columns.push(column);
            }
        }
        let text = row.to_string().into_boxed_str();
        self.bytes = self.bytes + text.len() - self.texts[i].len();
        self.texts[i] = text;
        self.rows[i] = row;
    }
    fn rebuild(&mut self) {
        let rows = std::mem::take(&mut self.rows);
        *self = Table::from_rows(std::mem::take(&mut self.key), rows).expect("rows were checked");
    }
    fn changed(&mut self) {
        self.generation = GENERATION.fetch_add(1, Relaxed);
        self.groups.get_mut().clear();
        self.orders.get_mut().clear();
        if self
            .columns
            .iter()
            .any(|c| c.dead > 4096 && c.dead * 2 > c.text.len())
        {
            self.rebuild();
        }
    }
    fn write_json(&self, out: &mut String) {
        out.reserve(self.bytes);
        out.push_str("{\"key\":");
        out.push_str(&Value::String(self.key.clone()).to_string());
        out.push_str(",\"rows\":[");
        for (i, text) in self.texts.iter().enumerate() {
            if i > 0 {
                out.push(',');
            }
            out.push_str(text);
        }
        out.push_str("]}");
    }
    pub fn groups(&self, field: &str) -> Groups {
        if let Some(groups) = self.groups.borrow().get(field) {
            return groups.clone();
        }
        let mut groups: Vec<(Value, Vec<usize>)> = Vec::new();
        let mut lookup = HashMap::new();
        for (i, row) in self.rows.iter().enumerate() {
            let value = &row[field];
            let next = groups.len();
            let group = *lookup.entry(value.to_string()).or_insert(next);
            if group == groups.len() {
                groups.push((value.clone(), Vec::new()));
            }
            groups[group].1.push(i);
        }
        let groups = Rc::new(groups);
        let mut cache = self.groups.borrow_mut();
        if cache.len() >= 4 {
            cache.clear();
        }
        cache.insert(field.into(), groups.clone());
        groups
    }
    /// Every row in the order of `sort`; equal rows keep their dataset order.
    fn order(&self, sort: &[(&str, bool)]) -> Rc<Vec<u32>> {
        let spec: String = sort
            .iter()
            .map(|(f, desc)| format!("{f}\0{desc}\0"))
            .collect();
        if let Some(order) = self.orders.borrow().get(&spec) {
            return order.clone();
        }
        let keys: Vec<Vec<SortKey>> = sort
            .iter()
            .map(|(field, _)| {
                self.rows
                    .iter()
                    .map(|row| match &row[*field] {
                        Value::String(s) => SortKey::Text(s),
                        v => match v.as_f64() {
                            Some(n) => SortKey::Number(n, v),
                            None => SortKey::Other(display(v)),
                        },
                    })
                    .collect()
            })
            .collect();
        let mut order: Vec<u32> = (0..self.rows.len() as u32).collect();
        order.sort_unstable_by(|a, b| {
            for (keys, (_, desc)) in keys.iter().zip(sort) {
                let order = keys[*a as usize].cmp(&keys[*b as usize]);
                if order != Ordering::Equal {
                    return if *desc { order.reverse() } else { order };
                }
            }
            a.cmp(b)
        });
        let order = Rc::new(order);
        let mut cache = self.orders.borrow_mut();
        if cache.len() >= 4 {
            cache.clear();
        }
        cache.insert(spec, order.clone());
        order
    }
    fn text_hits(&self, needle: &str, fields: Option<&[&str]>) -> Vec<bool> {
        let mut hits = vec![false; self.rows.len()];
        let columns: Vec<&Column> = match fields {
            Some(fields) => fields
                .iter()
                .filter_map(|f| self.names.get(*f))
                .map(|c| &self.columns[*c])
                .collect(),
            None => self.columns.iter().collect(),
        };
        let finder = Finder::new(needle.as_bytes());
        if needle.as_bytes().contains(&0) {
            for (i, hit) in hits.iter_mut().enumerate() {
                *hit = columns
                    .iter()
                    .any(|c| c.get(i).is_some_and(|s| finder.find(s).is_some()));
            }
        } else {
            for column in columns {
                column.mark(&finder, &mut hits);
            }
        }
        hits
    }
    /// The row with this key.
    pub fn position(&self, key: &Value) -> Option<usize> {
        key_text(key).and_then(|k| self.keys.get(&k).copied())
    }
    pub fn indices(&self, query: &Value) -> Result<Vec<usize>, String> {
        self.select(&Query::parse(query)?, usize::MAX)
    }
    /// Matching rows in query order, at most `limit` of them.
    fn select(&self, q: &Query, limit: usize) -> Result<Vec<usize>, String> {
        let mut hits =
            (!q.needle.is_empty()).then(|| self.text_hits(&q.needle, q.fields.as_deref()));
        // A row equal to or containing a filter's value contains its lowercase
        // text, so one scan of the field's text narrows the rows to check.
        for f in &q.filters {
            let needle = f.finder.needle();
            if !matches!(f.op, "eq" | "contains") || needle.is_empty() || needle.contains(&0) {
                continue;
            }
            let mut found = vec![false; self.rows.len()];
            if let Some(c) = self.names.get(f.field) {
                self.columns[*c].mark(&f.finder, &mut found);
            }
            if let Some(hits) = &mut hits {
                for (hit, found) in hits.iter_mut().zip(found) {
                    *hit &= found;
                }
            } else {
                hits = Some(found);
            }
        }
        let keep = |i: usize| {
            if hits.as_ref().is_some_and(|h| !h[i]) {
                return false;
            }
            let row = &self.rows[i];
            q.filters.iter().all(|f| {
                let a = &row[f.field];
                match f.op {
                    "eq" => a == f.value,
                    "ne" => a != f.value,
                    "in" => f.value.as_array().is_some_and(|v| v.contains(a)),
                    "lt" => compare(a, f.value) == Ordering::Less,
                    "gt" => compare(a, f.value) == Ordering::Greater,
                    "contains" => self
                        .names
                        .get(f.field)
                        .and_then(|c| self.columns[*c].get(i))
                        .is_some_and(|s| f.finder.find(s).is_some()),
                    _ => false,
                }
            })
        };
        // Exact primary-key reads (detail panes) never scan the whole dataset.
        if let Some(f) = q
            .filters
            .iter()
            .find(|f| f.field == self.key && f.op == "eq")
        {
            return Ok(key_text(f.value)
                .and_then(|k| self.keys.get(&k).copied())
                .filter(|i| keep(*i))
                .into_iter()
                .take(limit)
                .collect());
        }
        if q.sort.is_empty() {
            Ok((0..self.rows.len())
                .filter(|i| keep(*i))
                .take(limit)
                .collect())
        } else {
            Ok(self
                .order(&q.sort)
                .iter()
                .map(|i| *i as usize)
                .filter(|i| keep(*i))
                .take(limit)
                .collect())
        }
    }
}
enum SortKey<'a> {
    Number(f64, &'a Value),
    Text(&'a str),
    Other(String),
}
impl SortKey<'_> {
    fn text(&self) -> Cow<'_, str> {
        match self {
            SortKey::Number(_, v) => Cow::Owned(display(v)),
            SortKey::Text(s) => Cow::Borrowed(s),
            SortKey::Other(s) => Cow::Borrowed(s),
        }
    }
    /// The same order as `compare`.
    fn cmp(&self, other: &Self) -> Ordering {
        match (self, other) {
            (SortKey::Number(a, _), SortKey::Number(b, _)) => a.total_cmp(b),
            (SortKey::Text(a), SortKey::Text(b)) => a.cmp(b),
            _ => self.text().cmp(&other.text()),
        }
    }
}
struct Filter<'a> {
    field: &'a str,
    op: &'a str,
    value: &'a Value,
    finder: Finder<'static>,
}
struct Query<'a> {
    needle: String,
    fields: Option<Vec<&'a str>>,
    filters: Vec<Filter<'a>>,
    sort: Vec<(&'a str, bool)>,
}
impl<'a> Query<'a> {
    fn parse(q: &'a Value) -> Result<Self, String> {
        validate_query(q)?;
        Ok(Query {
            needle: q["text"]["value"].as_str().unwrap_or("").to_lowercase(),
            fields: q["text"]["fields"]
                .as_array()
                .map(|fs| fs.iter().filter_map(Value::as_str).collect()),
            filters: q["where"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|f| Filter {
                    field: f["field"].as_str().unwrap_or(""),
                    op: f["op"].as_str().unwrap_or(""),
                    value: &f["value"],
                    finder: Finder::new(display(&f["value"]).to_lowercase().as_bytes())
                        .into_owned(),
                })
                .collect(),
            sort: q["sort"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|s| (s["field"].as_str().unwrap_or(""), s["dir"] == "desc"))
                .collect(),
        })
    }
    fn all(&self) -> bool {
        self.needle.is_empty() && self.filters.is_empty()
    }
}
pub fn display(v: &Value) -> String {
    match v {
        Value::Null => String::new(),
        Value::String(s) => s.clone(),
        _ => v.to_string(),
    }
}
fn compare(a: &Value, b: &Value) -> Ordering {
    match (a.as_f64(), b.as_f64()) {
        (Some(a), Some(b)) => a.total_cmp(&b),
        _ => display(a).cmp(&display(b)),
    }
}
fn validate_query(q: &Value) -> Result<(), String> {
    if !q.is_null() && !q.is_object() {
        return Err("Dataset query must be an object".into());
    }
    for field in ["where", "sort"] {
        if !q[field].is_null() && !q[field].is_array() {
            return Err(format!("Dataset {field} must be an array"));
        }
    }
    if !q["limit"].is_null() && q["limit"].as_u64().is_none() {
        return Err("Dataset limit must be a non-negative integer".into());
    }
    if !q["text"].is_null() {
        if !q["text"].is_object() || !q["text"]["value"].is_string() {
            return Err("Dataset text needs a string value".into());
        }
        if !q["text"]["fields"].is_null()
            && !q["text"]["fields"]
                .as_array()
                .is_some_and(|v| v.iter().all(Value::is_string))
        {
            return Err("Dataset text fields must be an array of strings".into());
        }
    }
    for f in q["where"].as_array().into_iter().flatten() {
        if !f["field"].is_string()
            || !matches!(
                f["op"].as_str(),
                Some("eq" | "ne" | "in" | "lt" | "gt" | "contains")
            )
        {
            return Err("Invalid dataset filter field or operator".into());
        }
        if f["op"] == "in" && !f["value"].is_array() {
            return Err("Dataset in filter needs an array".into());
        }
    }
    for s in q["sort"].as_array().into_iter().flatten() {
        if !s["field"].is_string() || !matches!(s["dir"].as_str(), Some("asc" | "desc")) {
            return Err("Invalid dataset sort".into());
        }
    }
    Ok(())
}
#[derive(Default)]
pub struct Datasets {
    tables: BTreeMap<String, Rc<Table>>,
    pub version: u64,
    pub saved_version: u64,
    lazy: Option<Value>,
    pub read_only: bool,
}
/// Takes the tables out of a saved snapshot without copying their rows.
fn parse_snapshot(value: Value) -> Result<BTreeMap<String, (String, Vec<Value>)>, String> {
    let mut tables = BTreeMap::new();
    match value {
        Value::Null => {}
        Value::Object(map) => {
            for (name, mut table) in map {
                let key = table["key"]
                    .as_str()
                    .ok_or("Dataset snapshot tables need a key")?
                    .to_owned();
                let rows = rows_array(&mut table)?;
                tables.insert(name, (key, rows));
            }
        }
        _ => return Err("Dataset snapshot must be an object".into()),
    }
    Ok(tables)
}
impl Datasets {
    pub fn load(&mut self, value: Value) {
        self.tables.clear();
        self.lazy = Some(value);
        self.version = 0;
        self.saved_version = 0;
    }
    fn ready(&mut self) -> Result<(), String> {
        if let Some(v) = self.lazy.take() {
            self.tables = parse_snapshot(v)?
                .into_iter()
                .map(|(name, (key, rows))| Ok((name, Rc::new(Table::from_rows(key, rows)?))))
                .collect::<Result<_, String>>()?;
        }
        Ok(())
    }
    pub fn table(&mut self, name: &str) -> Result<Rc<Table>, String> {
        self.ready()?;
        Ok(self
            .tables
            .get(name)
            .cloned()
            .unwrap_or_else(|| Rc::new(Table::new("id".into()))))
    }
    pub fn snapshot(&mut self) -> Result<Value, String> {
        self.ready()?;
        Ok(Value::Object(
            self.tables
                .iter()
                .map(|(k, t)| (k.clone(), json!({"key":t.key,"rows":t.rows})))
                .collect(),
        ))
    }
    /// `snapshot().to_string()`, written straight from the rows.
    pub fn snapshot_text(&mut self) -> Result<String, String> {
        self.ready()?;
        let mut out = String::with_capacity(self.bytes_with(None));
        out.push('{');
        for (i, (name, table)) in self.tables.iter().enumerate() {
            if i > 0 {
                out.push(',');
            }
            out.push_str(&Value::String(name.clone()).to_string());
            out.push(':');
            table.write_json(&mut out);
        }
        out.push('}');
        Ok(out)
    }
    /// Serialized size of every table, with `replace` standing in for one.
    fn bytes_with(&self, replace: Option<(&str, usize)>) -> usize {
        let mut sizes: Vec<(usize, usize)> = self
            .tables
            .iter()
            .filter(|(name, _)| replace.is_none_or(|(r, _)| r != name.as_str()))
            .map(|(name, t)| (json_len(name), t.bytes))
            .collect();
        if let Some((name, bytes)) = replace {
            sizes.push((json_len(name), bytes));
        }
        2 + sizes.iter().map(|(n, b)| n + 1 + b).sum::<usize>() + sizes.len().saturating_sub(1)
    }
    pub fn dirty(&self) -> bool {
        self.version != self.saved_version
    }
    pub fn request(&mut self, op: &str, name: &str, args: &Value) -> Result<Value, String> {
        if matches!(op, "set" | "patch" | "remove" | "clear") {
            return self.mutate(op, name, args.clone());
        }
        self.read(op, name, args)
    }
    /// `request` for an operation whose arguments the caller no longer needs.
    pub fn request_owned(&mut self, op: &str, name: &str, args: Value) -> Result<Value, String> {
        if matches!(op, "set" | "patch" | "remove" | "clear") {
            return self.mutate(op, name, args);
        }
        self.read(op, name, &args)
    }
    fn mutate(&mut self, op: &str, name: &str, mut args: Value) -> Result<Value, String> {
        self.ready()?;
        if self.read_only {
            return Err("badge must be pure".into());
        }
        if name.is_empty() || name.len() > 128 {
            return Err("Dataset name must be 1–128 bytes".into());
        }
        let too_big = || Err("View datasets exceed the 16 MB limit".into());
        match op {
            "set" => {
                let key = args["options"]["key"].as_str().unwrap_or("id").to_owned();
                let table = Table::from_rows(key, rows_array(&mut args)?)?;
                if self.bytes_with(Some((name, table.bytes))) > MAX_BYTES {
                    return too_big();
                }
                self.tables.insert(name.into(), Rc::new(table));
            }
            "patch" => {
                let rows = rows_array(&mut args)?;
                let existed = self.tables.contains_key(name);
                let mut slot = self
                    .tables
                    .remove(name)
                    .unwrap_or_else(|| Rc::new(Table::new("id".into())));
                // Check everything and measure the result before changing anything.
                let mut updates: Vec<(Option<usize>, String, Map<String, Value>)> = vec![];
                let mut pending: HashMap<String, usize> = HashMap::new();
                let checked = (|| {
                    for row in rows {
                        let object = checked_object(row)?;
                        let key = key_text(object.get(&slot.key).unwrap_or(&Value::Null))
                            .ok_or(KEY_ERROR)?;
                        if let Some(&u) = pending.get(&key) {
                            updates[u].2.extend(object);
                        } else if let Some(&i) = slot.keys.get(&key) {
                            let mut merged = slot.rows[i].as_object().expect("checked row").clone();
                            merged.extend(object);
                            pending.insert(key.clone(), updates.len());
                            updates.push((Some(i), key, merged));
                        } else {
                            pending.insert(key.clone(), updates.len());
                            updates.push((None, key, object));
                        }
                    }
                    let mut bytes = slot.bytes as isize;
                    let mut count = slot.rows.len();
                    for (index, _, row) in &updates {
                        let len = Value::Object(row.clone()).to_string().len() as isize;
                        match index {
                            Some(i) => bytes += len - slot.texts[*i].len() as isize,
                            None => {
                                bytes += len + isize::from(count > 0);
                                count += 1;
                            }
                        }
                    }
                    if self.bytes_with(Some((name, bytes as usize))) > MAX_BYTES {
                        return Err("View datasets exceed the 16 MB limit".to_string());
                    }
                    Ok(())
                })();
                if checked.is_ok() && !updates.is_empty() {
                    let table = Rc::make_mut(&mut slot);
                    for (index, key, row) in updates {
                        match index {
                            Some(i) => table.update(i, Value::Object(row)),
                            None => table.append(key, Value::Object(row)),
                        }
                    }
                    table.changed();
                }
                if checked.is_ok() || existed {
                    self.tables.insert(name.into(), slot);
                }
                checked?;
            }
            "remove" => {
                let keys: HashSet<_> = args["keys"]
                    .as_array()
                    .ok_or("Dataset keys must be an array")?
                    .iter()
                    .map(Value::to_string)
                    .collect();
                let mut table = self
                    .tables
                    .remove(name)
                    .unwrap_or_else(|| Rc::new(Table::new("id".into())));
                let table_mut = Rc::make_mut(&mut table);
                let key = table_mut.key.clone();
                table_mut
                    .rows
                    .retain(|r| !keys.contains(&r[&key].to_string()));
                table_mut.rebuild();
                self.tables.insert(name.into(), table);
            }
            "clear" => {
                let key = self.table(name)?.key.clone();
                self.tables.insert(name.into(), Rc::new(Table::new(key)));
            }
            _ => unreachable!(),
        }
        self.version += 1;
        Ok(Value::Null)
    }
    fn read(&mut self, op: &str, name: &str, args: &Value) -> Result<Value, String> {
        let table = self.table(name)?;
        let query = Query::parse(args)?;
        match op {
            "count" if query.all() => Ok(json!(table.rows.len())),
            "count" => Ok(json!(table.select(&query, usize::MAX)?.len())),
            "rows" => {
                let limit = args["limit"].as_u64().unwrap_or(200).min(MAX_ROWS as u64) as usize;
                Ok(Value::Array(
                    table
                        .select(&query, limit)?
                        .into_iter()
                        .map(|i| table.rows[i].clone())
                        .collect(),
                ))
            }
            "aggregate" => {
                let group_by = args["groupBy"].as_str();
                let ops: Vec<(&String, Option<&str>, &str)> = args["ops"]
                    .as_object()
                    .into_iter()
                    .flatten()
                    .map(|(alias, spec)| {
                        (
                            alias,
                            spec["op"].as_str(),
                            spec["field"].as_str().unwrap_or(""),
                        )
                    })
                    .collect();
                // Groups come from the table's cached grouping, in their
                // value's JSON order; a query narrows each one.
                let selected = (!query.all()).then(|| {
                    let mut mask = vec![false; table.rows.len()];
                    table.select(&query, usize::MAX).map(|rows| {
                        for i in rows {
                            mask[i] = true;
                        }
                        mask
                    })
                });
                let selected = selected.transpose()?;
                let cached;
                let all = [(Value::Null, (0..table.rows.len()).collect::<Vec<_>>())];
                let source: &[(Value, Vec<usize>)] = match group_by {
                    Some(field) => {
                        cached = table.groups(field);
                        &cached
                    }
                    None => &all,
                };
                let mut groups: Vec<(String, &Value, Vec<usize>)> = source
                    .iter()
                    .map(|(value, rows)| {
                        let rows = match &selected {
                            Some(mask) => rows.iter().copied().filter(|i| mask[*i]).collect(),
                            None => rows.clone(),
                        };
                        (value.to_string(), value, rows)
                    })
                    .filter(|(_, _, rows)| !rows.is_empty())
                    .collect();
                if groups.len() > MAX_ROWS {
                    return Err("Dataset aggregate exceeds 2000 groups".into());
                }
                groups.sort_by(|a, b| a.0.cmp(&b.0));
                let mut result = Vec::new();
                for (_, group, indices) in groups {
                    let mut item = json!({"group":group,"count":indices.len()});
                    for (alias, op, field) in &ops {
                        let values: Vec<f64> = indices
                            .iter()
                            .filter_map(|i| table.rows[*i][*field].as_f64())
                            .collect();
                        item[alias.as_str()] = match op {
                            Some("count") => json!(indices.len()),
                            Some("sum") => json!(values.iter().sum::<f64>()),
                            Some("avg") => {
                                if values.is_empty() {
                                    Value::Null
                                } else {
                                    json!(values.iter().sum::<f64>() / values.len() as f64)
                                }
                            }
                            Some("min") => values
                                .into_iter()
                                .reduce(f64::min)
                                .map_or(Value::Null, |n| json!(n)),
                            Some("max") => values
                                .into_iter()
                                .reduce(f64::max)
                                .map_or(Value::Null, |n| json!(n)),
                            _ => return Err("Unknown dataset aggregate operator".into()),
                        };
                    }
                    result.push(item);
                }
                Ok(json!(result))
            }
            _ => Err("Unknown dataset operation".into()),
        }
    }
}

/// Validate at the broker boundary too; scripts never choose a storage path.
pub fn validate_snapshot(value: &Value) -> Result<(), String> {
    if value.to_string().len() > MAX_BYTES {
        return Err("View datasets exceed the 16 MB limit".into());
    }
    if !value.is_null() && !value.is_object() {
        return Err("Dataset snapshot must be an object".into());
    }
    for (name, table) in value.as_object().into_iter().flatten() {
        if name.is_empty() || name.len() > 128 {
            return Err("Invalid dataset name".into());
        }
        let key = table["key"]
            .as_str()
            .ok_or("Dataset snapshot tables need a key")?;
        let rows = table["rows"]
            .as_array()
            .ok_or("Dataset rows must be an array")?;
        let mut keys = HashSet::with_capacity(rows.len());
        for row in rows {
            let object = row.as_object().ok_or("Dataset rows must be flat objects")?;
            if object.values().any(|v| v.is_array() || v.is_object()) {
                return Err("Dataset rows must contain only scalar values".into());
            }
            let key = key_text(object.get(key).unwrap_or(&Value::Null)).ok_or(KEY_ERROR)?;
            if !keys.insert(key) {
                return Err(KEY_ERROR.into());
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn data() -> Datasets {
        let mut d = Datasets::default();
        d.request("set","x",&json!({"options":{"key":"id"},"rows":[{"id":1,"name":"Éclair","score":2,"team":"a"},{"id":2,"name":"SECOND","score":10,"team":"b"},{"id":3,"name":"third","score":5,"team":"a"}]})).unwrap();
        d
    }
    #[test]
    fn query_semantics_and_stable_numeric_sort() {
        let mut d = data();
        for (op, v, n) in [
            ("eq", json!(5), 1),
            ("ne", json!(5), 2),
            ("in", json!([2, 5]), 2),
            ("lt", json!(5), 1),
            ("gt", json!(5), 1),
        ] {
            assert_eq!(
                d.request(
                    "count",
                    "x",
                    &json!({"where":[{"field":"score","op":op,"value":v}]})
                )
                .unwrap(),
                n
            );
        }
        assert_eq!(
            d.request(
                "count",
                "x",
                &json!({"text":{"value":"éC","fields":["name"]}})
            )
            .unwrap(),
            1
        );
        assert_eq!(
            d.request(
                "count",
                "x",
                &json!({"where":[{"field":"name","op":"contains","value":"second"}]})
            )
            .unwrap(),
            1
        );
        let rows = d
            .request(
                "rows",
                "x",
                &json!({"sort":[{"field":"score","dir":"desc"}],"limit":2}),
            )
            .unwrap();
        assert_eq!(rows[0]["id"], 2);
        assert_eq!(rows[1]["id"], 3);
        assert!(
            d.request("rows", "x", &json!({"where":[{"field":"id","op":"oops"}]}))
                .is_err()
        );
        let g = d.request("aggregate","x",&json!({"groupBy":"team","ops":{"total":{"op":"sum","field":"score"},"mean":{"op":"avg","field":"score"}}})).unwrap();
        assert_eq!(g[0], json!({"group":"a","count":2,"total":7.0,"mean":3.5}));
    }
    #[test]
    fn bounded_reads_atomic_mutations_and_lazy_roundtrip() {
        let mut d = data();
        d.request(
            "patch",
            "x",
            &json!({"rows":[{"id":1,"score":3},{"id":4,"name":"fourth"}]}),
        )
        .unwrap();
        assert_eq!(d.request("count", "x", &Value::Null).unwrap(), 4);
        d.request("remove", "x", &json!({"keys":[2,3]})).unwrap();
        let snapshot = d.snapshot().unwrap();
        assert!(
            d.request("set", "x", &json!({"rows":[{"id":1},{"id":1}]}))
                .is_err()
        );
        assert!(
            d.request(
                "set",
                "x",
                &json!({"rows":[{"id":9,"blob":"x".repeat(MAX_BYTES)}]})
            )
            .is_err()
        );
        assert_eq!(d.snapshot().unwrap(), snapshot);
        let mut restored = Datasets::default();
        restored.load(snapshot);
        assert!(!restored.dirty());
        assert_eq!(restored.request("count", "x", &Value::Null).unwrap(), 2);
        restored.request("clear", "x", &Value::Null).unwrap();
        assert_eq!(restored.request("count", "x", &Value::Null).unwrap(), 0);
        d.request(
            "set",
            "many",
            &json!({"rows":(0..3000).map(|id|json!({"id":id})).collect::<Vec<_>>()}),
        )
        .unwrap();
        assert_eq!(
            d.request("rows", "many", &Value::Null)
                .unwrap()
                .as_array()
                .unwrap()
                .len(),
            200
        );
        assert_eq!(
            d.request("rows", "many", &json!({"limit":99999}))
                .unwrap()
                .as_array()
                .unwrap()
                .len(),
            MAX_ROWS
        );
        assert_eq!(
            d.request("rows", "many", &json!({"limit":0})).unwrap(),
            json!([])
        );
    }

    #[test]
    fn snapshot_text_size_and_patch_match_serialization() {
        let mut d = data();
        d.request(
            "set",
            "other key",
            &json!({"options":{"key":"k"},"rows":[{"k":"a\"b","v":null,"w":true}]}),
        )
        .unwrap();
        d.request("patch", "x", &json!({"rows":[{"id":2,"name":"Ünï","extra":1.5},{"id":7,"name":"new"},{"id":7,"score":1}]})).unwrap();
        let snapshot = d.snapshot().unwrap();
        assert_eq!(d.snapshot_text().unwrap(), snapshot.to_string());
        assert_eq!(d.bytes_with(None), snapshot.to_string().len());
        assert_eq!(
            snapshot["x"]["rows"][1],
            json!({"id":2,"name":"Ünï","score":10,"team":"b","extra":1.5})
        );
        assert_eq!(
            snapshot["x"]["rows"][3],
            json!({"id":7,"name":"new","score":1})
        );
        // A patched row is found by its new text and no longer by its old text.
        let count = |d: &mut Datasets, text: &str| {
            d.request("count", "x", &json!({"text":{"value":text}}))
                .unwrap()
        };
        assert_eq!(count(&mut d, "ünï"), 1);
        assert_eq!(count(&mut d, "second"), 0);
        assert_eq!(count(&mut d, "1.5"), 1);
        // A failed patch changes nothing, even part way through.
        assert!(
            d.request(
                "patch",
                "x",
                &json!({"rows":[{"id":1,"score":4},{"id":8,"bad":[1]}]})
            )
            .is_err()
        );
        assert!(
            d.request(
                "patch",
                "x",
                &json!({"rows":[{"id":1,"score":4},{"name":"no key"}]})
            )
            .is_err()
        );
        assert_eq!(d.snapshot().unwrap(), snapshot);
        // Removing rows keeps search, keys and size in step.
        d.request("remove", "x", &json!({"keys":[2]})).unwrap();
        assert_eq!(count(&mut d, "ünï"), 0);
        assert_eq!(
            d.request(
                "rows",
                "x",
                &json!({"where":[{"field":"id","op":"eq","value":7}]})
            )
            .unwrap()[0]["name"],
            "new"
        );
        assert_eq!(d.snapshot_text().unwrap().len(), d.bytes_with(None));
        // Many in-place updates compact the search text and keep answers.
        for n in 0..3000 {
            d.request(
                "patch",
                "x",
                &json!({"rows":[{"id":1,"name":format!("name {n}")}]}),
            )
            .unwrap();
        }
        assert_eq!(count(&mut d, "name 2999"), 1);
        assert_eq!(count(&mut d, "name 2998"), 0);
        assert!(
            d.tables["x"]
                .columns
                .iter()
                .all(|c| c.dead <= 4096 || c.dead * 2 <= c.text.len())
        );
    }
    #[cfg(feature = "native")]
    #[test]
    fn script_calls_send_each_operation_its_arguments() {
        let engine = crate::script::Engine::new(
            "host.data.set('x',[{id:1,n:'a'},{id:2,n:'b'},{id:3,n:'c'}]);host.data.patch('x',[{id:2,n:'B'}]);host.data.remove('x',[1]);\
             const left=host.data.rows('x').map(r=>r.n).join();host.data.clear('x');\
             view({state:{left,after:host.data.count('x')},render:()=>Page()})",
            &json!({}),
        )
        .unwrap();
        let state = engine.checkpoint().unwrap();
        assert_eq!(
            (state["left"].as_str(), state["after"].as_u64()),
            (Some("B,c"), Some(0))
        );
    }
    /// `cargo test -p meep-script dataset_bench -- --ignored --nocapture`
    /// (add `--profile fast` for optimized numbers). Mirrors the Showcase's
    /// Performance tab: 100,000 rows sent as ten JSON chunks, then searched.
    #[test]
    #[ignore]
    fn dataset_bench() {
        use std::time::Instant;
        const F: [&str; 16] = [
            "Ada",
            "Grace",
            "Alan",
            "Linus",
            "Margaret",
            "Ken",
            "Barbara",
            "Dennis",
            "Frances",
            "Edsger",
            "Radia",
            "Bjarne",
            "Hedy",
            "Guido",
            "Katherine",
            "Niklaus",
        ];
        const L: [&str; 17] = [
            "Lovelace",
            "Hopper",
            "Turing",
            "Torvalds",
            "Hamilton",
            "Thompson",
            "Liskov",
            "Ritchie",
            "Allen",
            "Dijkstra",
            "Perlman",
            "Stroustrup",
            "Lamarr",
            "van Rossum",
            "Johnson",
            "Wirth",
            "Kay",
        ];
        const T: [&str; 7] = [
            "Compilers",
            "Graphics",
            "Networking",
            "Storage",
            "Kernel",
            "Design",
            "Research",
        ];
        const S: [&str; 3] = ["Ready", "Pending", "Failed"];
        let row = |i: usize| json!({"id":i+1,"name":format!("{} {}",F[i%16],L[(i*7)%17]),"team":T[(i*3)%7],"status":S[(i*13)%3],"score":((i*7919)%10000) as f64/100.0});
        let ms = |t: Instant| t.elapsed().as_secs_f64() * 1000.0;
        let chunks: Vec<String> = (0..10)
            .map(|c| json!({"rows":(c*10000..(c+1)*10000).map(row).collect::<Vec<_>>(),"options":{"key":"id"}}).to_string())
            .collect();
        let mut d = Datasets::default();
        let mut each = vec![];
        let t = Instant::now();
        let parsed: Vec<Value> = chunks.iter().map(|c| c.parse::<Value>().unwrap()).collect();
        eprintln!("\n  (JSON parse of all chunks: {:.1} ms)", ms(t));
        drop(parsed);
        let t = Instant::now();
        for (c, text) in chunks.iter().enumerate() {
            let t = Instant::now();
            let args = text.parse::<Value>().unwrap();
            d.request(if c == 0 { "set" } else { "patch" }, "bench", &args)
                .unwrap();
            each.push(format!("{:.0}", ms(t)));
        }
        eprintln!(
            "\nDATASET BENCH debug_assertions={}",
            cfg!(debug_assertions)
        );
        eprintln!(
            "  ingest 10 x 10k chunks:   {:8.1} ms  [{}]",
            ms(t),
            each.join(" ")
        );
        let one = json!({"rows":(0..100000).map(row).collect::<Vec<_>>(),"options":{"key":"id"}})
            .to_string();
        let t = Instant::now();
        d.request("set", "bench", &one.parse::<Value>().unwrap())
            .unwrap();
        eprintln!("  ingest one 100k set:      {:8.1} ms", ms(t));
        let time = |label: &str, d: &mut Datasets, op: &str, q: Value| {
            let t = Instant::now();
            let mut n = 0;
            let mut out = Value::Null;
            while n < 5 || t.elapsed().as_millis() < 200 {
                out = d.request(op, "bench", &q).unwrap();
                n += 1;
            }
            let shown = if out.is_array() {
                json!(out.as_array().unwrap().len())
            } else {
                out
            };
            eprintln!("  {label:<26}{:8.3} ms  ({shown})", ms(t) / n as f64);
        };
        time("count, no query:", &mut d, "count", json!({}));
        time(
            "count, text 'ada' 3 cols:",
            &mut d,
            "count",
            json!({"text":{"value":"ada","fields":["name","team","status"]}}),
        );
        time(
            "count, text 'ada' all:",
            &mut d,
            "count",
            json!({"text":{"value":"ada"}}),
        );
        time(
            "count, text 'zzz' 3 cols:",
            &mut d,
            "count",
            json!({"text":{"value":"zzz","fields":["name","team","status"]}}),
        );
        time(
            "count, where team eq:",
            &mut d,
            "count",
            json!({"where":[{"field":"team","op":"eq","value":"Kernel"}]}),
        );
        time(
            "rows, sort name, 50:",
            &mut d,
            "rows",
            json!({"sort":[{"field":"name","dir":"asc"}],"limit":50}),
        );
        time(
            "rows, sort score, 50:",
            &mut d,
            "rows",
            json!({"sort":[{"field":"score","dir":"desc"}],"limit":50}),
        );
        time(
            "rows, 'ada' + sort name:",
            &mut d,
            "rows",
            json!({"text":{"value":"ada","fields":["name","team","status"]},"sort":[{"field":"name","dir":"asc"}],"limit":50}),
        );
        time(
            "aggregate by team:",
            &mut d,
            "aggregate",
            json!({"groupBy":"team","ops":{"s":{"op":"sum","field":"score"}}}),
        );
        d.version += 1;
        let t = Instant::now();
        let snapshot = d.snapshot_text().unwrap();
        eprintln!(
            "  snapshot text:            {:8.1} ms  ({} bytes)",
            ms(t),
            snapshot.len()
        );
        let parsed = snapshot.parse::<Value>().unwrap();
        let t = Instant::now();
        validate_snapshot(&parsed).unwrap();
        eprintln!("  broker validate_snapshot: {:8.1} ms", ms(t));
        let t = Instant::now();
        let mut restored = Datasets::default();
        restored.load(parsed);
        restored.request("count", "bench", &json!({})).unwrap();
        eprintln!("  restore + first read:     {:8.1} ms", ms(t));
        let t = Instant::now();
        d.request("patch", "bench", &json!({"rows":[{"id":5,"score":1.0}]}))
            .unwrap();
        eprintln!("  patch one row of 100k:    {:8.1} ms", ms(t));
    }
}
