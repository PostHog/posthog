//! Container decoding with avsc's results, including its errors and its silent cases.

use std::cell::RefCell;

use super::schema::Schema;
use super::value::{AvroMap, AvroValue};
use super::{AvroError, Container, MAGIC};

/// A read past the end moves the position past the end and does not fail. The caller checks `is_valid`, as avsc does.
pub(crate) struct Tap<'a> {
    pub buf: &'a [u8],
    pub pos: usize,
    /// Values that consumed no bytes. A few bytes can declare any number of them, so they share one budget.
    pub empty_values: u64,
}

/// avsc's `isSafeLong` bound: one less than 2^53 - 1 on each side, for its rounding.
const SAFE_LONG: f64 = 9007199254740990.0;

const MAX_ARRAY_LENGTH: f64 = 4_294_967_295.0;

/// Node runs out of memory on a large count of empty values, and this port stops instead.
const MAX_EMPTY_VALUES: u64 = 1 << 20;

fn precision_loss() -> AvroError {
    AvroError::Decode("potential precision loss".to_string())
}

impl<'a> Tap<'a> {
    pub fn new(buf: &'a [u8]) -> Self {
        Self {
            buf,
            pos: 0,
            empty_values: 0,
        }
    }

    fn count_empty_value(&mut self) -> Result<(), AvroError> {
        self.empty_values += 1;
        if self.empty_values > MAX_EMPTY_VALUES {
            return Err(AvroError::Decode("too many empty records".to_string()));
        }
        Ok(())
    }

    pub fn is_valid(&self) -> bool {
        self.pos <= self.buf.len()
    }

    fn invalidate(&mut self) {
        self.pos = self.buf.len() + 1;
    }

    /// A byte, or 0 past the end as `buf[pos]` gives `undefined` in JavaScript.
    fn byte(&mut self) -> u8 {
        let b = self.buf.get(self.pos).copied().unwrap_or(0);
        self.pos = self.pos.saturating_add(1);
        b
    }

    /// The Node consumer patches avsc 5.7.9 to stop at 10 bytes, so an 11th byte invalidates the tap and every long is finite. See PORTING.md.
    pub fn read_long(&mut self) -> f64 {
        let mut n: i32 = 0;
        let mut k = 0;
        let mut b;
        let mut h;
        loop {
            b = self.byte();
            h = b & 0x80;
            n |= ((b & 0x7f) as i32) << k;
            k += 7;
            if h == 0 || k >= 28 {
                break;
            }
        }
        if h != 0 {
            let mut f = n as f64;
            let mut fk = 268_435_456.0;
            let mut read = 4;
            loop {
                if read == 10 {
                    self.invalidate();
                    return 0.0;
                }
                read += 1;
                b = self.byte();
                f += (b & 0x7f) as f64 * fk;
                fk *= 128.0;
                if b & 0x80 == 0 {
                    break;
                }
            }
            return (if f % 2.0 != 0.0 { -(f + 1.0) } else { f }) / 2.0;
        }
        ((n >> 1) ^ -(n & 1)) as f64
    }

    fn skip_long(&mut self) {
        while self.byte() & 0x80 != 0 {}
    }

    /// avsc moves `pos` by any length, but every later read past the end gives zeros, so the exact position does not matter.
    pub fn read_fixed(&mut self, len: usize) -> Option<&'a [u8]> {
        let start = self.pos;
        match start.checked_add(len) {
            Some(end) if end <= self.buf.len() => {
                self.pos = end;
                Some(&self.buf[start..end])
            }
            _ => {
                self.invalidate();
                None
            }
        }
    }

    /// A negative or oversized length leaves avsc's `pos` past the end, which is invalid too.
    pub fn read_bytes(&mut self) -> Option<&'a [u8]> {
        let len = self.read_long();
        let remaining = self.buf.len().saturating_sub(self.pos) as f64;
        if !(0.0..=remaining).contains(&len) {
            self.invalidate();
            return None;
        }
        self.read_fixed(len as usize)
    }

    /// Invalid UTF-8 decodes with U+FFFD for each maximal invalid subpart, as Node does.
    pub fn read_string(&mut self) -> Option<String> {
        self.read_bytes().map(|b| match std::str::from_utf8(b) {
            Ok(text) => text.to_owned(),
            Err(_) => String::from_utf8_lossy(b).into_owned(),
        })
    }

    fn remaining(&self) -> usize {
        self.buf.len().saturating_sub(self.pos)
    }

    /// A negative count carries a byte size, which avsc skips.
    fn read_array_size(&mut self) -> f64 {
        let n = self.read_long();
        if n < 0.0 {
            self.skip_long();
            return -n;
        }
        n
    }
}

/// Running out of data is not an error here, because the caller sees it through `is_valid`.
pub(crate) fn read_value(tap: &mut Tap<'_>, schema: &Schema) -> Result<AvroValue, AvroError> {
    Ok(match schema {
        Schema::Null => AvroValue::Null,
        Schema::Boolean => AvroValue::Boolean(tap.byte() != 0),
        Schema::Int => AvroValue::Int(tap.read_long() as i64),
        Schema::Long => {
            let n = tap.read_long();
            if !(-SAFE_LONG..=SAFE_LONG).contains(&n) {
                return Err(precision_loss());
            }
            AvroValue::Long(n as i64)
        }
        Schema::Float => {
            let b = tap.read_fixed(4);
            AvroValue::Float(b.map_or(0.0, |b| f32::from_le_bytes(b.try_into().unwrap()) as f64))
        }
        Schema::Double => {
            let b = tap.read_fixed(8);
            AvroValue::Double(b.map_or(0.0, |b| f64::from_le_bytes(b.try_into().unwrap())))
        }
        Schema::Bytes => AvroValue::Bytes(tap.read_bytes().map(<[u8]>::to_vec).unwrap_or_default()),
        Schema::String => AvroValue::String(tap.read_string().unwrap_or_default()),
        Schema::Fixed(f) => AvroValue::Fixed(
            tap.read_fixed(f.size)
                .map(<[u8]>::to_vec)
                .unwrap_or_default(),
        ),
        Schema::Enum(e) => {
            let index = tap.read_long();
            match e.symbols.get(index as usize).filter(|_| index >= 0.0) {
                Some(symbol) => AvroValue::Enum(symbol.clone()),
                None => {
                    return Err(AvroError::Decode(format!(
                        "invalid {} enum index: {}",
                        e.name,
                        crate::js::number_to_string(index)
                    )))
                }
            }
        }
        Schema::Union(branches) => {
            let index = tap.read_long();
            match branches
                .get(index as usize)
                .filter(|_| index >= 0.0 && index.fract() == 0.0)
            {
                Some(branch) => read_value(tap, branch)?,
                None => {
                    return Err(AvroError::Decode(format!(
                        "invalid union index: {}",
                        crate::js::number_to_string(index)
                    )))
                }
            }
        }
        Schema::Array(items) => {
            let mut out = Vec::new();
            let mut first_batch = true;
            loop {
                let mut n = tap.read_long();
                if n == 0.0 || n.is_nan() {
                    break;
                }
                if n < 0.0 {
                    n = -n;
                    tap.skip_long();
                }
                // avsc sizes the array from the first count with `new Array(n)`.
                if first_batch && n > MAX_ARRAY_LENGTH {
                    return Err(AvroError::Decode("Invalid array length".to_string()));
                }
                first_batch = false;
                if !tap.is_valid() {
                    break;
                }
                // A capacity hint only: a count can claim more items than the data holds.
                out.reserve((n as usize).min(tap.remaining()).min(4096));
                for _ in 0..n as u64 {
                    let start = tap.pos;
                    out.push(read_value(tap, items)?);
                    if tap.pos == start {
                        tap.count_empty_value()?;
                    }
                    if !tap.is_valid() {
                        return Ok(AvroValue::Array(out));
                    }
                }
            }
            AvroValue::Array(out)
        }
        Schema::Map(values) => {
            let mut out = AvroMap::new();
            loop {
                let n = tap.read_array_size();
                if n == 0.0 || n.is_nan() || !tap.is_valid() {
                    break;
                }
                for _ in 0..n as u64 {
                    // avsc names an unreadable key `undefined`, and the record fails as a truncated block either way.
                    let key = tap.read_string().unwrap_or_else(|| "undefined".to_string());
                    let value = read_value(tap, values)?;
                    out.assign(key, value);
                    if !tap.is_valid() {
                        return Ok(AvroValue::Map(out));
                    }
                }
            }
            AvroValue::Map(out)
        }
        Schema::Record(record) => {
            let mut fields = Vec::with_capacity(record.fields.len());
            for field in &record.fields {
                fields.push((field.name.clone(), read_value(tap, &field.schema)?));
            }
            AvroValue::Record(fields)
        }
    })
}

struct Header {
    meta: Vec<(String, Vec<u8>)>,
    sync: [u8; 16],
}

/// `None` means it ran out of data, which avsc treats as "wait for more" and ends with no metadata.
fn read_header(tap: &mut Tap<'_>) -> Option<Header> {
    tap.read_fixed(4)?;
    let mut meta = Vec::new();
    loop {
        let n = tap.read_array_size();
        if n == 0.0 || n.is_nan() || !tap.is_valid() {
            break;
        }
        for _ in 0..n as u64 {
            let key = tap.read_string();
            let value = tap.read_bytes().map(<[u8]>::to_vec);
            if !tap.is_valid() {
                return None;
            }
            let key = key.unwrap_or_default();
            // A plain-object assignment: a later duplicate wins.
            match meta
                .iter_mut()
                .find(|(k, _): &&mut (String, Vec<u8>)| *k == key)
            {
                Some(entry) => entry.1 = value.unwrap_or_default(),
                None => meta.push((key, value.unwrap_or_default())),
            }
        }
    }
    let sync = tap.read_fixed(16)?;
    if !tap.is_valid() {
        return None;
    }
    Some(Header {
        meta,
        sync: sync.try_into().expect("16 bytes"),
    })
}

/// A larger stated size goes through the streaming decoder, which grows its buffer instead of trusting the header.
const MAX_PRESIZED_FRAME: u64 = 64 << 20;

const DEFAULT_WINDOW_LOG_MAX: u32 = 27;

/// The one-shot decoder skips zstd's default window limit, which Node enforces, so such frames take the streaming path.
fn declared_window_exceeds_default(data: &[u8]) -> bool {
    let Some(&descriptor) = data.get(4) else {
        return true;
    };
    if descriptor & 0x20 != 0 {
        return false;
    }
    let Some(&window) = data.get(5) else {
        return true;
    };
    let log = u32::from(window >> 3) + 10;
    let base = 1u64 << log;
    base + (base / 8) * u64::from(window & 7) > 1u64 << DEFAULT_WINDOW_LOG_MAX
}

thread_local! {
    /// A zstd context is large to set up, so each thread keeps one.
    static DECOMPRESSOR: RefCell<Option<zstd::bulk::Decompressor<'static>>> = const { RefCell::new(None) };
}

/// Any input other than one sized frame, or a failure there, takes the streaming path, whose result counts.
fn inflate(data: &[u8]) -> std::io::Result<Vec<u8>> {
    use zstd::zstd_safe::{find_frame_compressed_size, get_frame_content_size};
    if let (Ok(len), Ok(Some(size))) = (
        find_frame_compressed_size(data),
        get_frame_content_size(data),
    ) {
        if len == data.len() && size <= MAX_PRESIZED_FRAME && !declared_window_exceeds_default(data)
        {
            let fast = DECOMPRESSOR.with(|cell| {
                let mut slot = cell.borrow_mut();
                let decompressor = match slot.as_mut() {
                    Some(d) => d,
                    None => slot.insert(zstd::bulk::Decompressor::new()?),
                };
                let inflated = decompressor.decompress(data, size as usize);
                // A failed frame can leave state in the context, so the next frame gets a new one.
                if !matches!(&inflated, Ok(out) if out.len() as u64 == size) {
                    *slot = None;
                }
                inflated
            });
            if let Ok(inflated) = fast {
                if inflated.len() as u64 == size {
                    return Ok(inflated);
                }
            }
        }
    }
    zstd::stream::decode_all(data)
}

/// Only the zstandard codec is registered, as in `decodeLogRecords`.
pub fn decode_container(buf: &[u8]) -> Result<Container, AvroError> {
    if buf.len() < MAGIC.len() {
        return Err(AvroError::NoMetadata);
    }
    if buf[..4] != MAGIC {
        return Err(AvroError::InvalidMagic);
    }
    let mut tap = Tap::new(buf);
    let header = read_header(&mut tap).ok_or(AvroError::NoMetadata)?;
    let meta = |key: &str| header.meta.iter().find(|(k, _)| k == key).map(|(_, v)| v);
    let text = |v: &Vec<u8>| match std::str::from_utf8(v) {
        Ok(text) => text.to_owned(),
        Err(_) => String::from_utf8_lossy(v).into_owned(),
    };
    let codec = meta("avro.codec")
        .map(text)
        .unwrap_or_else(|| "null".to_string());
    if codec != "zstandard" {
        return Err(AvroError::UnknownCodec(codec));
    }
    let schema_json = meta("avro.schema")
        .map(text)
        .ok_or_else(|| AvroError::Schema("missing avro.schema".to_string()))?;
    let schema = Schema::parse_json_cached(&schema_json)?;

    // avsc checks every complete block's sync marker before any block decompresses, and it never reads an incomplete trailing block.
    let mut blocks = Vec::new();
    loop {
        // avsc reads the count as a `long`, which throws before the rest of the block is read.
        let count = tap.read_long();
        if !(-SAFE_LONG..=SAFE_LONG).contains(&count) {
            return Err(precision_loss());
        }
        let data = tap.read_bytes();
        let sync = tap.read_fixed(16);
        if !tap.is_valid() {
            break;
        }
        if sync != Some(&header.sync[..]) {
            return Err(AvroError::InvalidSyncMarker);
        }
        blocks.push((count, data.unwrap_or_default()));
        if tap.pos >= buf.len() {
            break;
        }
    }

    let mut records = Vec::new();
    let mut empty_values = 0u64;
    for (count, data) in blocks {
        let inflated =
            inflate(data).map_err(|_| AvroError::Decompression("zstandard".to_string()))?;
        // The sender controls `count`, so the reservation is bounded by bytes actually inflated.
        records.reserve(((count as i64).clamp(0, 4096) as usize).min(inflated.len()));
        // avsc keeps `count | 0`, and a negative count reads records until one fails.
        let mut remaining = i64::from((count as i64) as i32);
        let mut block = Tap::new(&inflated);
        block.empty_values = empty_values;
        while remaining != 0 {
            remaining -= 1;
            let start = block.pos;
            let value = read_value(&mut block, &schema)?;
            if !block.is_valid() {
                return Err(AvroError::Decode("truncated block".to_string()));
            }
            if block.pos == start {
                block.count_empty_value()?;
                if remaining < 0 {
                    return Err(AvroError::Decode("too many empty records".to_string()));
                }
            }
            records.push(value);
        }
        empty_values = block.empty_values;
    }

    Ok(Container {
        schema_json,
        schema,
        codec,
        records,
    })
}

#[cfg(test)]
mod tests {
    use super::Tap;

    #[test]
    fn read_long_stops_at_ten_bytes_like_the_patched_avsc() {
        let ten = [0xfe, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x01];
        let mut tap = Tap::new(&ten);
        assert_eq!(tap.read_long(), 9_223_372_036_854_775_807.0);
        assert!(tap.is_valid());

        let eleven = [0xff; 11];
        let mut tap = Tap::new(&eleven);
        assert_eq!(tap.read_long(), 0.0);
        assert!(!tap.is_valid());
    }
}
