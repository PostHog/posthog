//! InMemoryEmbeddingStore + InMemoryReportStore, ported from pipeline.py.
//! Rows are stored in arrival order; embeddings normalized at store time.

use crate::feats::{dot, normalize};
use rayon::prelude::*;
use std::collections::HashMap;

pub const SEARCH_LIMIT: usize = 10;
pub const SEARCH_WINDOW_SECS: f64 = 30.0 * 86400.0; // default; overridable per store

#[cfg(target_os = "macos")]
mod blas {
    // Apple Accelerate cblas_sgemm: C(m×n) = A(m×k) · B(n×k)ᵀ, row-major.
    extern "C" {
        fn cblas_sgemm(
            layout: i32,
            trans_a: i32,
            trans_b: i32,
            m: i32,
            n: i32,
            k: i32,
            alpha: f32,
            a: *const f32,
            lda: i32,
            b: *const f32,
            ldb: i32,
            beta: f32,
            c: *mut f32,
            ldc: i32,
        );
    }
    const ROW_MAJOR: i32 = 101;
    const NO_TRANS: i32 = 111;
    const TRANS: i32 = 112;

    pub fn sgemm_nt(a: &[f32], b: &[f32], c: &mut [f32], m: usize, n: usize, k: usize) {
        assert!(a.len() >= m * k && b.len() >= n * k && c.len() >= m * n);
        unsafe {
            cblas_sgemm(
                ROW_MAJOR,
                NO_TRANS,
                TRANS,
                m as i32,
                n as i32,
                k as i32,
                1.0,
                a.as_ptr(),
                k as i32,
                b.as_ptr(),
                k as i32,
                0.0,
                c.as_mut_ptr(),
                n as i32,
            );
        }
    }
}

#[derive(Clone)]
pub struct Candidate {
    pub row: usize,
    pub signal_id: String,
    pub report_id: String, // store-time report id ("" if none)
    pub distance: f64,
}

pub struct EmbeddingStore {
    pub dims: usize,
    pub matrix: Vec<f32>, // row-major, normalized rows
    pub n: usize,
    pub signal_ids: Vec<String>,
    pub contents: Vec<String>,
    pub report_ids: Vec<String>, // "" = none (unsearchable)
    pub source_products: Vec<String>,
    pub source_types: Vec<String>,
    pub source_ids: Vec<String>,
    pub timestamps: Vec<f64>,
    pub rows_by_report: HashMap<String, Vec<usize>>,
    pub row_by_signal_id: HashMap<String, usize>,
    pub neigh_scale: HashMap<String, f64>,
    pub window_secs: f64,
    rows_by_type: HashMap<(String, String), Vec<usize>>,
    // (selected row range) -> mean, per type: the newest-cap-in-window set changes
    // rarely between batches, so identical ranges reuse the mean bit-for-bit
    means_cache: HashMap<(String, String), ((usize, usize), Vec<f32>)>,
}

pub struct ReportView {
    /// most recent `cap` member rows (geometry sample)
    pub emb_rows: Vec<usize>,
    /// most recent `id_cap` member rows (content/id sample)
    pub content_rows: Vec<usize>,
    pub size: usize,
}

impl EmbeddingStore {
    pub fn new(dims: usize) -> Self {
        Self {
            dims,
            matrix: Vec::new(),
            n: 0,
            signal_ids: Vec::new(),
            contents: Vec::new(),
            report_ids: Vec::new(),
            source_products: Vec::new(),
            source_types: Vec::new(),
            source_ids: Vec::new(),
            timestamps: Vec::new(),
            rows_by_report: HashMap::new(),
            row_by_signal_id: HashMap::new(),
            neigh_scale: HashMap::new(),
            window_secs: SEARCH_WINDOW_SECS,
            rows_by_type: HashMap::new(),
            means_cache: HashMap::new(),
        }
    }

    #[inline]
    pub fn row(&self, i: usize) -> &[f32] {
        &self.matrix[i * self.dims..(i + 1) * self.dims]
    }

    #[allow(clippy::too_many_arguments)]
    pub fn store(
        &mut self,
        signal_id: String,
        content: String,
        embedding: &[f32],
        report_id: String,
        source_product: String,
        source_type: String,
        source_id: String,
        ts: f64,
        neigh_scale: Option<f64>,
    ) {
        if let Some(s) = neigh_scale {
            self.neigh_scale.insert(signal_id.clone(), s);
        }
        let row = self.n;
        self.matrix.extend_from_slice(&normalize(embedding));
        self.timestamps.push(ts);
        if !report_id.is_empty() {
            self.rows_by_report
                .entry(report_id.clone())
                .or_default()
                .push(row);
        }
        self.row_by_signal_id.insert(signal_id.clone(), row);
        self.rows_by_type
            .entry((source_product.clone(), source_type.clone()))
            .or_default()
            .push(row);
        self.signal_ids.push(signal_id);
        self.contents.push(content);
        self.report_ids.push(report_id);
        self.source_products.push(source_product);
        self.source_types.push(source_type);
        self.source_ids.push(source_id);
        self.n += 1;
    }

    pub fn merge_reports(&mut self, src: &str, dst: &str) {
        let rows = self.rows_by_report.remove(src).unwrap_or_default();
        for &r in &rows {
            self.report_ids[r] = dst.to_string();
        }
        if !rows.is_empty() {
            self.rows_by_report
                .entry(dst.to_string())
                .or_default()
                .extend(rows);
        }
    }

    /// Move an explicit subset of one report into another report.
    pub fn move_members(
        &mut self,
        src: &str,
        dst: &str,
        move_ids: &std::collections::HashSet<String>,
    ) -> usize {
        if src == dst || move_ids.is_empty() {
            return 0;
        }
        let rows = self.rows_by_report.get(src).cloned().unwrap_or_default();
        let (kept, moved): (Vec<usize>, Vec<usize>) = rows
            .into_iter()
            .partition(|row| !move_ids.contains(&self.signal_ids[*row]));
        if moved.is_empty() {
            return 0;
        }
        if kept.is_empty() {
            self.rows_by_report.remove(src);
        } else {
            self.rows_by_report.insert(src.to_string(), kept);
        }
        for &row in &moved {
            self.report_ids[row] = dst.to_string();
        }
        let count = moved.len();
        self.rows_by_report
            .entry(dst.to_string())
            .or_default()
            .extend(moved);
        count
    }

    /// Dense cosine matrix for two arbitrary report-member row lists.
    pub fn cross_similarities(&self, left: &[usize], right: &[usize]) -> Vec<f32> {
        if left.is_empty() || right.is_empty() {
            return Vec::new();
        }
        let mut left_values = Vec::with_capacity(left.len() * self.dims);
        let mut right_values = Vec::with_capacity(right.len() * self.dims);
        for &row in left {
            left_values.extend_from_slice(self.row(row));
        }
        for &row in right {
            right_values.extend_from_slice(self.row(row));
        }
        let mut output = vec![0.0f32; left.len() * right.len()];
        #[cfg(target_os = "macos")]
        blas::sgemm_nt(
            &left_values,
            &right_values,
            &mut output,
            left.len(),
            right.len(),
            self.dims,
        );
        #[cfg(not(target_os = "macos"))]
        output
            .par_chunks_mut(right.len())
            .enumerate()
            .for_each(|(left_index, row)| {
                for (right_index, value) in row.iter_mut().enumerate() {
                    *value = crate::feats::dot(
                        &left_values[left_index * self.dims..(left_index + 1) * self.dims],
                        &right_values[right_index * self.dims..(right_index + 1) * self.dims],
                    ) as f32;
                }
            });
        output
    }

    /// Move every member NOT in keep from `report_id` to `new_report_id`; returns moved count.
    pub fn split_report(
        &mut self,
        report_id: &str,
        keep: &std::collections::HashSet<String>,
        new_report_id: &str,
    ) -> usize {
        let rows = self
            .rows_by_report
            .get(report_id)
            .cloned()
            .unwrap_or_default();
        let (kept, moved): (Vec<usize>, Vec<usize>) = rows
            .into_iter()
            .partition(|r| keep.contains(&self.signal_ids[*r]));
        if moved.is_empty() {
            return 0;
        }
        self.rows_by_report.insert(report_id.to_string(), kept);
        for &r in &moved {
            self.report_ids[r] = new_report_id.to_string();
        }
        let n = moved.len();
        self.rows_by_report
            .entry(new_report_id.to_string())
            .or_default()
            .extend(moved);
        n
    }

    /// search_stacked: top-k cosine per query vector, pinned to `max_row` visibility
    /// and the 30-day window. Queries need not be normalized.
    pub fn search_stacked(
        &self,
        queries: &[Vec<f32>],
        now: f64,
        limit: usize,
        max_row: usize,
    ) -> Vec<Vec<Candidate>> {
        let visible = max_row.min(self.n);
        if visible == 0 {
            return queries.iter().map(|_| Vec::new()).collect();
        }
        let window_start = now - self.window_secs;
        let rows: Vec<usize> = (0..visible)
            .filter(|&r| {
                !self.report_ids[r].is_empty()
                    && self.timestamps[r] >= window_start
                    && self.timestamps[r] <= now
            })
            .collect();
        if rows.is_empty() {
            return queries.iter().map(|_| Vec::new()).collect();
        }
        let nq = queries.len();
        let normed: Vec<Option<Vec<f32>>> = queries
            .iter()
            .map(|q| {
                let nrm = crate::feats::norm(q);
                if nrm == 0.0 {
                    None
                } else {
                    Some(q.iter().map(|v| (*v as f64 / nrm) as f32).collect())
                }
            })
            .collect();
        let k = limit.min(rows.len());
        // Small stores: per-query parallel scan with bulk top-k selection (lower
        // constant factor). Large stores: blocked row scan — each row read once,
        // dotted against every query (GEMM-shaped, memory-bandwidth bound).
        if rows.len() < 32_768 {
            return normed
                .par_iter()
                .map(|qn| {
                    let Some(qn) = qn else { return Vec::new() };
                    let mut sims: Vec<(f64, usize)> =
                        rows.iter().map(|&r| (dot(self.row(r), qn), r)).collect();
                    sims.select_nth_unstable_by(k - 1, |a, b| {
                        b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1))
                    });
                    sims.truncate(k);
                    sims.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1)));
                    sims.into_iter()
                        .map(|(sim, r)| Candidate {
                            row: r,
                            signal_id: self.signal_ids[r].clone(),
                            report_id: self.report_ids[r].clone(),
                            distance: (1.0 - sim).max(0.0),
                        })
                        .collect()
                })
                .collect();
        }
        // Large store: GEMM over contiguous row blocks (Accelerate on macOS) — the
        // visible+window row set is a contiguous suffix because storage is arrival
        // order and streams are time-sorted; verify and fall back if not.
        let contiguous = rows.len() == rows[rows.len() - 1] - rows[0] + 1;
        let q_flat: Vec<f32> = {
            let mut flat = vec![0f32; nq * self.dims];
            for (qi, qn) in normed.iter().enumerate() {
                if let Some(qn) = qn {
                    flat[qi * self.dims..(qi + 1) * self.dims].copy_from_slice(qn);
                }
            }
            flat
        };
        const BLOCK: usize = 16_384;
        let blocks: Vec<(usize, usize)> = if contiguous {
            (0..rows.len())
                .step_by(BLOCK)
                .map(|s| (rows[0] + s, (s + BLOCK).min(rows.len()) - s))
                .collect()
        } else {
            Vec::new()
        };
        let block_tops: Vec<Vec<Vec<(f64, usize)>>> = if contiguous {
            blocks
                .par_iter()
                .map(|&(start, len)| {
                    #[cfg(target_os = "macos")]
                    {
                        let mut sims = vec![0f32; len * nq];
                        blas::sgemm_nt(
                            &self.matrix[start * self.dims..(start + len) * self.dims],
                            &q_flat,
                            &mut sims,
                            len,
                            nq,
                            self.dims,
                        );
                        let mut tops: Vec<Vec<(f64, usize)>> = vec![Vec::new(); nq];
                        for (qi, t) in tops.iter_mut().enumerate() {
                            if normed[qi].is_none() {
                                continue;
                            }
                            let mut col: Vec<(f64, usize)> = (0..len)
                                .map(|i| (sims[i * nq + qi] as f64, start + i))
                                .collect();
                            let kk = k.min(col.len());
                            col.select_nth_unstable_by(kk - 1, |a, b| {
                                b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1))
                            });
                            col.truncate(kk);
                            col.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1)));
                            *t = col;
                        }
                        tops
                    }
                    #[cfg(not(target_os = "macos"))]
                    {
                        let mut tops: Vec<Vec<(f64, usize)>> = vec![Vec::new(); nq];
                        for (qi, qn) in normed.iter().enumerate() {
                            let Some(qn) = qn else { continue };
                            let mut col: Vec<(f64, usize)> = (0..len)
                                .map(|i| (dot(self.row(start + i), qn), start + i))
                                .collect();
                            let kk = k.min(col.len());
                            col.select_nth_unstable_by(kk - 1, |a, b| {
                                b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1))
                            });
                            col.truncate(kk);
                            col.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1)));
                            tops[qi] = col;
                        }
                        tops
                    }
                })
                .collect()
        } else {
            rows.par_chunks(BLOCK)
                .map(|chunk| {
                    let mut tops: Vec<Vec<(f64, usize)>> = vec![Vec::new(); nq];
                    for (qi, qn) in normed.iter().enumerate() {
                        let Some(qn) = qn else { continue };
                        let mut col: Vec<(f64, usize)> =
                            chunk.iter().map(|&r| (dot(self.row(r), qn), r)).collect();
                        let kk = k.min(col.len());
                        col.select_nth_unstable_by(kk - 1, |a, b| {
                            b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1))
                        });
                        col.truncate(kk);
                        col.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1)));
                        tops[qi] = col;
                    }
                    tops
                })
                .collect()
        };
        (0..nq)
            .map(|qi| {
                if normed[qi].is_none() {
                    return Vec::new();
                }
                let mut merged: Vec<(f64, usize)> = block_tops
                    .iter()
                    .flat_map(|bt| bt[qi].iter().copied())
                    .collect();
                merged.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1)));
                merged.truncate(k);
                merged
                    .into_iter()
                    .map(|(sim, r)| Candidate {
                        row: r,
                        signal_id: self.signal_ids[r].clone(),
                        report_id: self.report_ids[r].clone(),
                        distance: (1.0 - sim).max(0.0),
                    })
                    .collect()
            })
            .collect()
    }

    /// type_means: mean normalized embedding per (product, type), trailing 30d,
    /// newest `per_type_cap` rows per type, only types with >= min_samples.
    /// Per-type row lists are arrival-ordered, so the selected set is a range;
    /// unchanged ranges reuse the cached mean.
    pub fn type_means(&mut self, now: f64, max_row: usize) -> HashMap<(String, String), Vec<f32>> {
        let visible = max_row.min(self.n);
        let window_start = now - 30.0 * 86400.0;
        const PER_TYPE_CAP: usize = 1000;
        const MIN_SAMPLES: usize = 25;
        let mut out = HashMap::new();
        let mut cache = std::mem::take(&mut self.means_cache);
        for (key, rows) in &self.rows_by_type {
            // visible prefix (rows ascend), then the in-window suffix of it
            let vis = rows.partition_point(|&r| r < visible);
            let prefix = &rows[..vis];
            let lo = prefix.partition_point(|&r| self.timestamps[r] < window_start);
            let hi = prefix.partition_point(|&r| self.timestamps[r] <= now);
            if hi <= lo {
                continue;
            }
            let sel = &prefix[lo.max(hi.saturating_sub(PER_TYPE_CAP))..hi];
            if sel.len() < MIN_SAMPLES {
                continue;
            }
            let range = (sel[0], sel[sel.len() - 1]);
            if let Some((cached_range, mean)) = cache.get(key) {
                if *cached_range == range {
                    out.insert(key.clone(), mean.clone());
                    continue;
                }
            }
            let mut mean = vec![0f64; self.dims];
            for &r in sel {
                for (acc, x) in mean.iter_mut().zip(self.row(r)) {
                    *acc += *x as f64;
                }
            }
            let n = sel.len() as f64;
            let mean: Vec<f32> = mean.into_iter().map(|x| (x / n) as f32).collect();
            cache.insert(key.clone(), (range, mean.clone()));
            out.insert(key.clone(), mean);
        }
        self.means_cache = cache;
        out
    }

    /// report_view: most recent `cap` members for geometry, `id_cap` for contents/ids.
    pub fn report_view(&self, report_id: &str, cap: usize, id_cap: usize) -> Option<ReportView> {
        let rows = self.rows_by_report.get(report_id)?;
        if rows.is_empty() {
            return None;
        }
        let take = |c: usize| rows[rows.len().saturating_sub(c)..].to_vec();
        Some(ReportView {
            emb_rows: take(cap),
            content_rows: take(id_cap),
            size: rows.len(),
        })
    }

    pub fn neigh_scale_of(&self, signal_id: &str) -> f64 {
        *self.neigh_scale.get(signal_id).unwrap_or(&1.0)
    }
}

/// Report id redirect map (merge chains) — InMemoryReportStore.resolve/merge.
#[derive(Default)]
pub struct ReportStore {
    redirects: HashMap<String, String>,
}

impl ReportStore {
    pub fn resolve(&self, report_id: &str) -> String {
        let mut cur = report_id;
        let mut seen = 0;
        while let Some(nxt) = self.redirects.get(cur) {
            cur = nxt;
            seen += 1;
            if seen > 10_000 {
                break; // cycle guard (shouldn't happen)
            }
        }
        cur.to_string()
    }

    pub fn merge(&mut self, src: &str, dst: &str) {
        let s = self.resolve(src);
        let d = self.resolve(dst);
        if s != d {
            self.redirects.insert(s, d);
        }
    }
}
