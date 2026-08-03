//! Browser-side deterioration scoring.
//!
//! This crate evaluates a model bundle exported by `inference/wasm_export.py`.
//! It is deliberately the only executable part of the deployment: the bundle
//! carries constants, never code, so a tampered bundle can corrupt a score but
//! cannot run anything.
//!
//! The privacy property this exists to provide is that lab values never leave
//! the client. Scoring happens here; only generalized, non-identifying output
//! is eligible to be submitted anywhere.

use serde::{Deserialize, Serialize};
use wasm_bindgen::prelude::*;

/// One decision tree, stored as parallel arrays indexed by node id.
///
/// Node-per-struct layouts chase pointers; parallel slices keep the hot loop
/// scanning contiguous memory, which matters because a bundle can hold several
/// hundred trees scored per patient.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Tree {
    pub feature: Vec<i32>,
    pub threshold: Vec<f64>,
    pub left: Vec<i32>,
    pub right: Vec<i32>,
    pub value: Vec<f64>,
    pub missing: Vec<i32>,
}

impl Tree {
    /// Walk one row to a leaf and return its contribution.
    ///
    /// `inclusive` selects `<=` (scikit-learn, LightGBM) over `<` (XGBoost).
    /// Getting this wrong shifts only rows sitting exactly on a threshold, so
    /// it survives casual testing and corrupts predictions in production.
    fn score(&self, row: &[f64], inclusive: bool) -> Result<f64, ScoreError> {
        let mut node: usize = 0;
        // A malformed bundle could encode a cycle; bound the walk by the node
        // count so a bad model cannot hang the browser tab.
        let max_steps = self.feature.len() + 1;

        for _ in 0..max_steps {
            let split_feature = self.feature[node];
            if split_feature < 0 {
                return Ok(self.value[node]);
            }

            let index = split_feature as usize;
            let x = *row.get(index).ok_or(ScoreError::FeatureIndexOutOfRange {
                index,
                len: row.len(),
            })?;

            let next = if x.is_nan() {
                self.missing[node]
            } else if (inclusive && x <= self.threshold[node])
                || (!inclusive && x < self.threshold[node])
            {
                self.left[node]
            } else {
                self.right[node]
            };

            if next < 0 || next as usize >= self.feature.len() {
                return Err(ScoreError::MalformedTree);
            }
            node = next as usize;
        }

        Err(ScoreError::MalformedTree)
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ModelSpec {
    pub trees: Vec<Tree>,
    pub base_score: f64,
    pub learning_rate: f64,
    pub weight: f64,
    #[serde(default)]
    pub split_inclusive: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(tag = "method", rename_all = "lowercase")]
pub enum Calibration {
    /// Piecewise-linear interpolation over isotonic breakpoints.
    Isotonic { x: Vec<f64>, y: Vec<f64> },
    /// Two-parameter sigmoid.
    Platt { coef: f64, intercept: f64 },
}

impl Calibration {
    fn apply(&self, score: f64) -> f64 {
        match self {
            Calibration::Isotonic { x, y } => interpolate(x, y, score),
            Calibration::Platt { coef, intercept } => sigmoid(coef * score + intercept),
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Preprocessing {
    None,
    ZScore {
        columns: Vec<String>,
        mean: Vec<f64>,
        scale: Vec<f64>,
        fill: Vec<f64>,
    },
    MinMax {
        columns: Vec<String>,
        min: Vec<f64>,
        scale: Vec<f64>,
        fill: Vec<f64>,
    },
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Bundle {
    pub format_version: u32,
    pub feature_names: Vec<String>,
    pub models: std::collections::BTreeMap<String, ModelSpec>,
    pub preprocessing: Preprocessing,
    pub calibration: Option<Calibration>,
    #[serde(default)]
    pub metadata: serde_json::Value,
}

#[derive(Debug)]
pub enum ScoreError {
    FeatureIndexOutOfRange { index: usize, len: usize },
    MalformedTree,
    WrongFeatureCount { expected: usize, got: usize },
}

impl std::fmt::Display for ScoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ScoreError::FeatureIndexOutOfRange { index, len } => write!(
                f,
                "tree splits on feature {index} but only {len} features were supplied"
            ),
            ScoreError::MalformedTree => write!(f, "tree contains an invalid child index"),
            ScoreError::WrongFeatureCount { expected, got } => write!(
                f,
                "expected {expected} features, got {got}; feature order is part \
                 of the model contract and a mismatched vector would score the \
                 wrong columns"
            ),
        }
    }
}

fn sigmoid(x: f64) -> f64 {
    1.0 / (1.0 + (-x).exp())
}

/// Linear interpolation with clamping, matching `numpy.interp`.
fn interpolate(xs: &[f64], ys: &[f64], value: f64) -> f64 {
    if xs.is_empty() {
        return value;
    }
    if value <= xs[0] {
        return ys[0];
    }
    if value >= xs[xs.len() - 1] {
        return ys[ys.len() - 1];
    }

    // partition_point is a binary search; isotonic tables can hold thousands
    // of breakpoints and this runs per patient.
    let upper = xs.partition_point(|&x| x < value).max(1);
    let (x0, x1) = (xs[upper - 1], xs[upper]);
    let (y0, y1) = (ys[upper - 1], ys[upper]);

    if (x1 - x0).abs() < f64::EPSILON {
        return y1;
    }
    y0 + (y1 - y0) * (value - x0) / (x1 - x0)
}

impl Bundle {
    /// Score one already-preprocessed feature vector.
    pub fn score_row(&self, row: &[f64]) -> Result<f64, ScoreError> {
        if row.len() != self.feature_names.len() {
            return Err(ScoreError::WrongFeatureCount {
                expected: self.feature_names.len(),
                got: row.len(),
            });
        }

        let mut blended = 0.0;
        for spec in self.models.values() {
            let mut margin = spec.base_score;
            for tree in &spec.trees {
                margin += tree.score(row, spec.split_inclusive)? * spec.learning_rate;
            }
            blended += spec.weight * sigmoid(margin);
        }

        Ok(match &self.calibration {
            Some(calibration) => calibration.apply(blended),
            None => blended,
        })
    }

    /// Apply the training-time scaler to raw lab values.
    ///
    /// The browser must reproduce preprocessing exactly. Refitting a scaler on
    /// client data would shift every feature and invalidate the thresholds
    /// baked into the trees, while looking perfectly reasonable.
    pub fn preprocess(&self, raw: &mut [f64]) {
        match &self.preprocessing {
            Preprocessing::None => {}
            Preprocessing::ZScore {
                mean, scale, fill, ..
            } => {
                for (i, value) in raw.iter_mut().enumerate().take(mean.len()) {
                    if value.is_nan() {
                        *value = fill[i];
                    }
                    *value = (*value - mean[i]) / scale[i];
                }
            }
            Preprocessing::MinMax {
                min, scale, fill, ..
            } => {
                for (i, value) in raw.iter_mut().enumerate().take(min.len()) {
                    if value.is_nan() {
                        *value = fill[i];
                    }
                    *value = (*value - min[i]) * scale[i];
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// JavaScript interface
// ---------------------------------------------------------------------------

#[wasm_bindgen]
pub struct Scorer {
    bundle: Bundle,
}

#[wasm_bindgen]
impl Scorer {
    /// Load a bundle from its JSON text.
    #[wasm_bindgen(constructor)]
    pub fn new(bundle_json: &str) -> Result<Scorer, JsValue> {
        let bundle: Bundle = serde_json::from_str(bundle_json)
            .map_err(|e| JsValue::from_str(&format!("invalid bundle: {e}")))?;

        if bundle.format_version != 1 {
            return Err(JsValue::from_str(&format!(
                "unsupported bundle format version {}; this build reads version 1",
                bundle.format_version
            )));
        }

        Ok(Scorer { bundle })
    }

    /// Feature names, in the order `score` expects them.
    #[wasm_bindgen(getter)]
    pub fn feature_names(&self) -> Vec<JsValue> {
        self.bundle
            .feature_names
            .iter()
            .map(|name| JsValue::from_str(name))
            .collect()
    }

    #[wasm_bindgen(getter)]
    pub fn n_features(&self) -> usize {
        self.bundle.feature_names.len()
    }

    /// Score one patient. NaN marks an unmeasured lab and takes the tree's
    /// missing branch rather than being imputed — which test was ordered is
    /// itself informative.
    pub fn score(&self, features: &[f64]) -> Result<f64, JsValue> {
        self.bundle
            .score_row(features)
            .map_err(|e| JsValue::from_str(&e.to_string()))
    }

    /// Score a batch laid out row-major, avoiding per-row JS boundary crossings.
    pub fn score_batch(&self, flat: &[f64], n_rows: usize) -> Result<Vec<f64>, JsValue> {
        let width = self.bundle.feature_names.len();
        if n_rows * width != flat.len() {
            return Err(JsValue::from_str(&format!(
                "expected {} values for {n_rows} rows of {width} features, got {}",
                n_rows * width,
                flat.len()
            )));
        }

        (0..n_rows)
            .map(|i| {
                self.bundle
                    .score_row(&flat[i * width..(i + 1) * width])
                    .map_err(|e| JsValue::from_str(&e.to_string()))
            })
            .collect()
    }

    /// Apply training-time preprocessing in place, returning the scaled vector.
    pub fn preprocess(&self, raw: &[f64]) -> Vec<f64> {
        let mut values = raw.to_vec();
        self.bundle.preprocess(&mut values);
        values
    }

    /// Risk band for a calibrated score. Thresholds match the server's bands
    /// so a client and the aggregate view never disagree about a patient.
    pub fn risk_band(&self, score: f64) -> String {
        match score {
            s if s < 0.30 => "low",
            s if s < 0.50 => "moderate",
            s if s < 0.70 => "high",
            _ => "critical",
        }
        .to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn stump(inclusive_threshold: f64) -> Tree {
        Tree {
            feature: vec![0, -1, -1],
            threshold: vec![inclusive_threshold, 0.0, 0.0],
            left: vec![1, -1, -1],
            right: vec![2, -1, -1],
            value: vec![0.0, -1.0, 1.0],
            missing: vec![1, -1, -1],
        }
    }

    #[test]
    fn routes_left_and_right() {
        let tree = stump(0.5);
        assert_eq!(tree.score(&[0.0], false).unwrap(), -1.0);
        assert_eq!(tree.score(&[1.0], false).unwrap(), 1.0);
    }

    #[test]
    fn missing_takes_designated_branch() {
        let tree = stump(0.5);
        assert_eq!(tree.score(&[f64::NAN], false).unwrap(), -1.0);
    }

    #[test]
    fn inclusive_flag_changes_boundary_routing() {
        let tree = stump(0.5);
        // A value exactly on the threshold is the only case the flag affects,
        // which is why it needs its own test.
        assert_eq!(tree.score(&[0.5], false).unwrap(), 1.0);
        assert_eq!(tree.score(&[0.5], true).unwrap(), -1.0);
    }

    #[test]
    fn rejects_short_feature_vector() {
        let tree = stump(0.5);
        assert!(matches!(
            tree.score(&[], false),
            Err(ScoreError::FeatureIndexOutOfRange { .. })
        ));
    }

    #[test]
    fn interpolation_clamps_outside_range() {
        let xs = vec![0.0, 1.0];
        let ys = vec![0.2, 0.8];
        assert_eq!(interpolate(&xs, &ys, -1.0), 0.2);
        assert_eq!(interpolate(&xs, &ys, 2.0), 0.8);
        assert!((interpolate(&xs, &ys, 0.5) - 0.5).abs() < 1e-12);
    }
}
