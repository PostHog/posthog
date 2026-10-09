use std::cell::RefCell;
use std::io;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock, PoisonError};
use std::thread::JoinHandle;
use std::time::Instant;

use metrics::counter;
use zstd::zstd_safe::{get_error_name, CCtx, CDict, CParameter, DCtx, DDict, ResetDirective};

/// Below this, zstd frame headers cost more than the dictionary saves.
const MIN_COMPRESSIBLE_BYTES: usize = 64;

/// Larger documents would fill the sample budget with outliers.
const MAX_SAMPLE_BYTES: usize = 16 * 1024;

/// zstd recommends samples of about 100 times the dictionary size.
const SAMPLE_BUDGET_BYTES: usize = 4 * 1024 * 1024;
const MIN_SAMPLES: usize = 1_000;

const DICTIONARY_MAX_BYTES: usize = 32 * 1024;

const COMPRESSION_LEVEL: i32 = 3;

pub(super) enum StoredProperties {
    Raw(Box<[u8]>),
    /// The frame omits the content size, so `raw_len` sizes the output buffer.
    ZstdDict {
        compressed: Box<[u8]>,
        raw_len: u32,
    },
}

impl StoredProperties {
    pub(super) fn raw_len(&self) -> usize {
        match self {
            Self::Raw(bytes) => bytes.len(),
            Self::ZstdDict { raw_len, .. } => *raw_len as usize,
        }
    }

    pub(super) fn stored_len(&self) -> usize {
        match self {
            Self::Raw(bytes) => bytes.len(),
            Self::ZstdDict { compressed, .. } => compressed.len(),
        }
    }
}

/// Enabled, it samples the first documents it encodes, trains one
/// dictionary from them, and compresses later documents with it.
/// Documents encoded before that, or after a failed training, stay raw.
pub(super) struct PropertiesCodec {
    /// Checked before the sample lock, so puts after the hand-off skip it.
    sampling: AtomicBool,
    samples: Mutex<Samples>,
    dictionary: Arc<OnceLock<Dictionary>>,
    training: Mutex<Option<JoinHandle<()>>>,
}

impl PropertiesCodec {
    pub(super) fn disabled() -> Self {
        Self::new(false)
    }

    pub(super) fn enabled() -> Self {
        Self::new(true)
    }

    fn new(sampling: bool) -> Self {
        Self {
            sampling: AtomicBool::new(sampling),
            samples: Mutex::new(Samples::default()),
            dictionary: Arc::new(OnceLock::new()),
            training: Mutex::new(None),
        }
    }

    pub(super) fn encode(&self, raw: Vec<u8>) -> StoredProperties {
        if raw.len() >= MIN_COMPRESSIBLE_BYTES {
            if let Some(dictionary) = self.dictionary.get() {
                if let Some(stored) = dictionary.compress(&raw) {
                    return stored;
                }
            } else if self.sampling.load(Ordering::Relaxed) {
                self.sample(&raw);
            }
        }
        StoredProperties::Raw(raw.into_boxed_slice())
    }

    pub(super) fn decode(&self, stored: &StoredProperties) -> Result<Vec<u8>, &'static str> {
        match stored {
            StoredProperties::Raw(bytes) => Ok(bytes.to_vec()),
            StoredProperties::ZstdDict {
                compressed,
                raw_len,
            } => self
                .dictionary
                .get()
                .ok_or("entry is compressed but the codec has no dictionary")?
                .decompress(compressed, *raw_len as usize),
        }
    }

    fn sample(&self, raw: &[u8]) {
        if raw.len() > MAX_SAMPLE_BYTES {
            return;
        }
        let mut samples = self.samples.lock().unwrap_or_else(PoisonError::into_inner);
        // Another put may have handed the samples off since the caller checked.
        if !self.sampling.load(Ordering::Relaxed) {
            return;
        }
        samples.data.extend_from_slice(raw);
        samples.sizes.push(raw.len());
        if samples.data.len() < SAMPLE_BUDGET_BYTES || samples.sizes.len() < MIN_SAMPLES {
            return;
        }
        self.sampling.store(false, Ordering::Relaxed);
        let samples = std::mem::take(&mut *samples);
        let dictionary = Arc::clone(&self.dictionary);
        // Training would stall an async worker for its whole run.
        let spawned = std::thread::Builder::new()
            .name("personhog-cache-dictionary".to_string())
            .spawn(move || train_and_install(samples, &dictionary));
        match spawned {
            Ok(handle) => {
                *self.training.lock().unwrap_or_else(PoisonError::into_inner) = Some(handle);
            }
            Err(e) => record_training_failure(&e),
        }
    }

    #[cfg(test)]
    fn with_dictionary(dictionary: Dictionary) -> Self {
        let codec = Self::disabled();
        assert!(codec.dictionary.set(dictionary).is_ok());
        codec
    }

    #[cfg(test)]
    fn wait_for_training(&self) -> bool {
        if let Some(handle) = self.training.lock().unwrap().take() {
            handle.join().expect("training thread panicked");
        }
        self.dictionary.get().is_some()
    }
}

#[derive(Default)]
struct Samples {
    data: Vec<u8>,
    sizes: Vec<usize>,
}

fn train_and_install(samples: Samples, slot: &OnceLock<Dictionary>) {
    let started = Instant::now();
    match Dictionary::train(&samples) {
        Ok(dictionary) => {
            let dictionary_bytes = dictionary.content_len;
            slot.get_or_init(|| dictionary);
            counter!("personhog_leader_cache_dictionary_trainings_total", "outcome" => "ok")
                .increment(1);
            tracing::info!(
                samples = samples.sizes.len(),
                sample_bytes = samples.data.len(),
                dictionary_bytes,
                elapsed_ms = started.elapsed().as_millis() as u64,
                "trained person properties compression dictionary"
            );
        }
        Err(e) => record_training_failure(&e),
    }
}

fn record_training_failure(error: &io::Error) {
    counter!("personhog_leader_cache_dictionary_trainings_total", "outcome" => "error")
        .increment(1);
    tracing::warn!(
        error = %error,
        "person properties dictionary training failed; cache entries stay uncompressed"
    );
}

struct Dictionary {
    cdict: CDict<'static>,
    ddict: DDict<'static>,
    content_len: usize,
}

impl Dictionary {
    fn train(samples: &Samples) -> io::Result<Self> {
        let content =
            zstd::dict::from_continuous(&samples.data, &samples.sizes, DICTIONARY_MAX_BYTES)?;
        let cdict = CDict::try_create(&content, COMPRESSION_LEVEL)
            .ok_or_else(|| io::Error::other("zstd could not prepare the compression dictionary"))?;
        let ddict = DDict::try_create(&content).ok_or_else(|| {
            io::Error::other("zstd could not prepare the decompression dictionary")
        })?;
        Ok(Self {
            cdict,
            ddict,
            content_len: content.len(),
        })
    }

    /// `None` when the output would not be smaller than the input.
    fn compress(&self, raw: &[u8]) -> Option<StoredProperties> {
        let raw_len = u32::try_from(raw.len()).ok()?;
        COMPRESSOR.with_borrow_mut(|cctx| {
            // Sized to the input, so zstd fails rather than write output that does not shrink.
            let mut compressed = Vec::with_capacity(raw.len());
            let written = cctx
                .ref_cdict(&self.cdict)
                .and_then(|_| cctx.compress2(&mut compressed, raw));
            // A failed frame leaves the context mid-session, where it refuses any dictionary change.
            cctx.reset(ResetDirective::SessionOnly)
                .expect("zstd documents that a session reset never fails");
            // The thread-local context outlives the dictionary, so it must not keep a pointer to it.
            cctx.disable_dictionary()
                .expect("a context in its init stage accepts a dictionary change");
            written.ok()?;
            (compressed.len() < raw.len()).then(|| StoredProperties::ZstdDict {
                compressed: compressed.into_boxed_slice(),
                raw_len,
            })
        })
    }

    fn decompress(&self, compressed: &[u8], raw_len: usize) -> Result<Vec<u8>, &'static str> {
        DECOMPRESSOR.with_borrow_mut(|dctx| {
            let mut raw = Vec::with_capacity(raw_len);
            dctx.decompress_using_ddict(&mut raw, compressed, &self.ddict)
                .map_err(get_error_name)?;
            if raw.len() != raw_len {
                return Err("decompressed length differs from the recorded length");
            }
            Ok(raw)
        })
    }
}

thread_local! {
    static COMPRESSOR: RefCell<CCtx<'static>> = RefCell::new(new_compressor());
    static DECOMPRESSOR: RefCell<DCtx<'static>> = RefCell::new(DCtx::create());
}

fn new_compressor() -> CCtx<'static> {
    let mut cctx = CCtx::create();
    // The entry stores the raw length, and the codec has one dictionary.
    cctx.set_parameter(CParameter::ContentSizeFlag(false))
        .expect("content size flag is a valid zstd parameter");
    cctx.set_parameter(CParameter::DictIdFlag(false))
        .expect("dictionary id flag is a valid zstd parameter");
    cctx
}

#[cfg(test)]
mod tests {
    use super::*;

    fn person_properties(seed: usize) -> Vec<u8> {
        let browsers = ["Chrome", "Safari", "Firefox", "Microsoft Edge"];
        let systems = ["Mac OS X", "Windows", "iOS", "Android", "Linux"];
        let countries = [("US", "United States"), ("DE", "Germany"), ("BR", "Brazil")];
        let browser = browsers[seed % browsers.len()];
        let os = systems[seed % systems.len()];
        let (country_code, country) = countries[seed % countries.len()];
        let url = format!("https://example.com/docs/page-{}?ref={}", seed % 211, seed);
        serde_json::to_vec(&serde_json::json!({
            "$browser": browser,
            "$browser_version": 100 + seed % 30,
            "$current_url": url,
            "$device_type": if seed.is_multiple_of(3) { "Mobile" } else { "Desktop" },
            "$geoip_country_code": country_code,
            "$geoip_country_name": country,
            "$geoip_city_name": format!("City {}", seed % 53),
            "$geoip_latitude": 40.0 + (seed % 100) as f64 / 7.0,
            "$geoip_longitude": -70.0 - (seed % 100) as f64 / 9.0,
            "$initial_browser": browser,
            "$initial_current_url": url,
            "$initial_os": os,
            "$initial_referring_domain": "$direct",
            "$initial_utm_source": format!("campaign-{}", seed % 17),
            "$os": os,
            "$pathname": format!("/docs/page-{}", seed % 211),
            "$referring_domain": "$direct",
            "email": format!("user{seed}@example.com"),
            "name": format!("User {seed}"),
            "plan": if seed.is_multiple_of(5) { "free" } else { "paid" },
        }))
        .unwrap()
    }

    fn trained_codec() -> PropertiesCodec {
        let mut samples = Samples::default();
        for seed in 0..4_000 {
            let document = person_properties(seed);
            samples.sizes.push(document.len());
            samples.data.extend_from_slice(&document);
        }
        PropertiesCodec::with_dictionary(Dictionary::train(&samples).unwrap())
    }

    #[test]
    fn documents_round_trip_and_only_shrinking_ones_are_compressed() {
        let codec = trained_codec();
        let mut state: u32 = 7;
        let incompressible: Vec<u8> = (0..512)
            .map(|_| {
                state = state.wrapping_mul(1_103_515_245).wrapping_add(12_345);
                (state >> 16) as u8
            })
            .collect();
        // Incompressible first: a failed frame must not stop later documents from compressing.
        for (document, expect_compressed) in [
            (incompressible, false),
            (person_properties(10_001), true),
            (br#"{"email":"a@example.com"}"#.to_vec(), false),
        ] {
            let stored = codec.encode(document.clone());
            assert_eq!(
                matches!(stored, StoredProperties::ZstdDict { .. }),
                expect_compressed
            );
            assert!(stored.stored_len() <= document.len());
            assert_eq!(stored.raw_len(), document.len());
            assert_eq!(codec.decode(&stored).unwrap(), document);
        }
    }

    #[test]
    fn only_an_enabled_codec_trains_from_the_documents_it_encodes() {
        for (codec, expect_trained) in [
            (PropertiesCodec::enabled(), true),
            (PropertiesCodec::disabled(), false),
        ] {
            let (mut seed, mut fed_bytes) = (0, 0);
            while seed < MIN_SAMPLES || fed_bytes < SAMPLE_BUDGET_BYTES {
                let document = person_properties(seed);
                fed_bytes += document.len();
                codec.encode(document);
                seed += 1;
            }
            assert_eq!(codec.wait_for_training(), expect_trained);
            let after = codec.encode(person_properties(seed));
            assert_eq!(
                matches!(after, StoredProperties::ZstdDict { .. }),
                expect_trained
            );
        }
    }
}
