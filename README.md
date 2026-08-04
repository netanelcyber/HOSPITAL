# PenuX-II

Prediction of clinical deterioration from **laboratory results**, using free-text
medical reports as an **auxiliary channel only**.

The lab panel is the primary signal. Clinical notes contribute context — negated
findings, comorbidity burden, triage acuity — but the model is built so that it
still predicts when no note exists.

---

## Architecture

```
                    ┌──────────────────────────────────────┐
   open datasets ──▶│  data/       cohort construction     │
   (MIMIC, eICU,    │              labelling, windows      │
    HiRID, NCBI)    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │  features/   LOINC harmonization     │
                    │              lab engineering         │
                    │              clinical NLP (ConText)  │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │  models/     GBDT ensemble           │
                    │              probability calibration │
                    └──────────────┬───────────────────────┘
                                   │  export
                    ┌──────────────▼───────────────────────┐
                    │  wasm/       browser-side scoring    │
                    │              labs never leave client │
                    └──────────────┬───────────────────────┘
                                   │  generalized only
                    ┌──────────────▼───────────────────────┐
                    │  api/        k-anonymity gate        │
                    │              differential privacy    │
                    └──────────────────────────────────────┘
```

---

## Data sources

Adapters normalize each source into one cohort schema. All are
**credentialed-access**: obtain them from PhysioNet under their DUA. Nothing is
downloaded automatically and no patient data is committed.

| Source | Stays | Setting |
|---|---|---|
| MIMIC-IV (hosp) | ~546,000 | Ward / internal medicine |
| MIMIC-IV-ED | ~425,000 | Emergency department |
| eICU-CRD | ~200,000 | 208 US hospitals |
| MIMIC-III | ~58,000 | ICU |
| HiRID | ~33,000 | ICU, Bern |
| AmsterdamUMCdb | ~23,000 | ICU, Amsterdam |
| SICdb | ~27,000 | ICU, Salzburg |

```python
from data.public_datasets import MultiSourceCohortBuilder, DeteriorationLabelConfig

cohort = (
    MultiSourceCohortBuilder(DeteriorationLabelConfig(
        observation_hours=24, prediction_horizon_hours=48,
    ))
    .add("mimic-iv", "/data/mimiciv")
    .add("eicu", "/data/eicu")
    .build()
)
```

MIMIC-IV's `labevents` is ~130M rows and is streamed in chunks rather than
loaded whole. Pooled cohorts keep a `source` column, because a model can score
well on a shuffled split by learning each site's assay quirks and then fail at
the first hospital it has not seen:

```python
pipeline.leave_one_site_out(cohort)
```

**NCBI** (`data/ncbi.py`) supplies GEO critical-illness cohorts with outcome
annotation for external validation, and MeSH entry terms for expanding the NLP
lexicon. GEO series are transcriptomic — they are validation cohorts, not a
substitute for the lab panel.

---

## LOINC harmonization

Every source names analytes differently: MIMIC uses numeric itemids, eICU free
text, AmsterdamUMCdb Dutch. All are mapped onto LOINC codes with per-analyte
unit conversion. Creatinine in µmol/L against mg/dL differs by a factor of
88.4; pooling them unconverted destroys the feature silently.

Values outside physiologically possible ranges are blanked as transcription
errors rather than kept as extreme patients.

---

## Clinical NLP

Keyword counting inverts the signal on clinical prose, because most of what a
note says about a finding is that it is *absent*. `features/clinical_nlp.py`
implements NegEx/ConText and resolves, per mention:

- **polarity** — "no evidence of sepsis" is not sepsis
- **experiencer** — "father had an MI" is not the patient
- **temporality** — "history of CHF" is not the current presentation
- **uncertainty** — "possible pneumonia" counts at half weight

Comorbidities are exempt from the temporality filter: chronic disease is
recorded in past history by definition, and zeroing it there discards exactly
the background risk it represents.

Every score is auditable per mention:

```python
featurizer.explain(note)
```
```
              concept          matched_text              section  negated  historical  family  active  weight
            infection                 fever      chief_complaint    False       False   False    True     1.5
               sepsis                sepsis                  hpi     True       False   False   False     0.0
             diabetes              diabetes past_medical_history    False        True   False    True     1.0
myocardial_infarction myocardial infarction       family_history    False       False    True   False     0.0
          hypotension           hypotensive           assessment    False       False   False    True     3.0
```

Contextual embeddings use Bio_ClinicalBERT, pre-trained on clinical notes so
that abbreviations like "s/p" and "w/o" tokenize meaningfully. Falls back to
TF-IDF + SVD when transformers is unavailable.

---

## Distributed WASM inference

Patient labs are the most sensitive data a hospital holds, and the safest
request is the one never sent. The trained model exports to a flat tree bundle
that scores **in the browser**; lab values never leave the client.

```python
from inference.wasm_export import export_bundle, score_bundle

bundle = export_bundle(result.ensemble, result.lab_extractor, result.calibrator)
```

`score_bundle` is a NumPy reference implementation kept solely to diff against
the Rust/WASM path. An exported model that scores differently in the browser
than in training is the failure this format exists to prevent, and it is
invisible without a reference. Current agreement: **2.8e-17**.

The bundle contains constants only — no code — so a corrupted bundle can wreck
a prediction but cannot execute anything.

---

## Anonymized distributed storage

The server is treated as honest-but-curious with breachable storage. It is
built so it *cannot* re-identify, not so it promises not to look.

1. **Client-side reduction.** The browser submits risk bands and coarsened lab
   bins — never raw values, identifiers, notes, or sub-day timestamps.
   Anonymizing server-side would be theatre; the raw data would already have
   crossed the network.
2. **k-anonymity.** Records stage until k others share their quasi-identifier
   signature. A record unique in age band × sex × lab pattern is
   re-identifiable however few fields it carries.
3. **Differential privacy.** Aggregate counts carry Laplace noise against a
   finite epsilon budget. Noise alone is not privacy — an attacker who asks
   1000 times averages it away — so an exhausted budget stops answering rather
   than degrading quietly.

Direct identifiers are not silently dropped; their presence is a protocol
violation and rejects the submission, because a client sending them has a bug
that would otherwise keep leaking.

---

## Evaluation

Rare-outcome prediction makes ROC-AUC flattering, so the reported metrics lead
with average precision and alert-burden recall — a deterioration alert is only
adopted if the ward can absorb its volume.

```
roc_auc                      average_precision
brier_raw                    brier_calibrated
recall_at_5pct_alerts        precision_at_5pct_alerts
recall_at_10pct_alerts       precision_at_10pct_alerts
```

Calibration is fitted on held-out validation data. A model optimized for
ranking produces scores that separate classes but are not probabilities, and
thresholds are set on calibrated risk.

---

## UpToDate

UpToDate is licensed content whose terms prohibit automated retrieval and
derivative use. Nothing here ingests it or trains on it.
`features/clinical_reference.py` provides link-out only: given a flagged
concept, it returns a deep link a clinician can open. Content stays on Wolters
Kluwer's side; only the URL crosses. API calls require the hospital's own
credentials and are disabled by default.

---

## Usage

```bash
pip install -r requirements.txt
```

```python
from training.pipeline import TrainingPipeline

pipeline = TrainingPipeline(use_clinical_nlp=True, harmonize_units=True)
result = pipeline.train(cohort, groups=cohort["patient_id"])

print(result.metrics)
print(result.feature_importance.head(10))
```

Grouped splitting is used when `groups` is supplied — the same patient in train
and test lets the model recognize them rather than generalize.

---

## PenuX interoperability

`data/penux_compat.py` reuses PenuX's conventions rather than inventing parallel
ones: `MIMIC_AUTOROOTS` and the same search order for dataset discovery, the same
MIMIC-III/IV layout detection, `HOURS_WINDOW` and `SEED`, and `_sanitize_tag`'s
artifact naming so both systems' outputs sort together.

```bash
python -m data.penux_compat /path/to/penux
```

Deliberate departures: PenuX forbids pandas and is PyTorch-first. PenuX-II pools
seven sources with differing schemas and units, where join and reshape logic is
the substance of the work, and uses tree ensembles because labs are tabular with
informative missingness — a neural net needs imputation to accept them, and
imputing a lab that was never ordered discards the fact that nobody ordered it.
The single-file constraint is honoured where it affects deployment:
`web/penux2.html` is one self-contained file.

## Differential from lab patterns

`features/lab_interpretation.py` produces a *differential*, not a diagnosis. The
distinction is not pedantry: isolated hyperkalaemia is a haemolysed sample far
more often than Addison's disease, and no text mining over the number 6.2 tells
those apart.

Pattern rules live in code, reviewable and version-controlled. Wikipedia is used
only to fetch a plain-language explanation for a condition the rules already
named — putting an anonymously editable source in the clinical path would make
the medicine unaccountable. Enrichment failure is non-fatal by design.

## Gastroenterology and hepatology

Hepatology suits a lab-only system unusually well: several scores that drive
real decisions are computed entirely from the panel. MELD allocates liver
transplants in the United States from four analytes; FIB-4 and APRI are
first-line non-invasive fibrosis tests.

`features/gastro.py` implements them as the **published formulae with their real
clamping rules**, not as a learned approximation. These are externally validated
on cohorts far larger than anything available here, and a clinician can
recompute MELD by hand and check it. Fitting a model to approximate a published
formula replaces a traceable calculation with an opaque one and loses accuracy
doing it.

Implemented: MELD / MELD-Na, FIB-4, APRI, R-factor, AST/ALT (De Ritis), Maddrey
DF, Atlanta lipase criterion, and the lab-derivable components of BISAP and
Glasgow-Blatchford — reported explicitly as partial, because presenting a
partial BISAP as a BISAP understates severity in exactly the sick patients it
exists to find.

Indeterminate zones are reported, not collapsed. FIB-4 between its cutoffs
catches roughly a third of patients, and the honest output there is
"elastography is the next step", not a forced call.

### Trained GI model

`training/gastro_model.py` fits and — more importantly — honestly evaluates a
diagnosis model against the scores it would replace.

With ~20 cirrhosis events in 234 admissions, the ten-events-per-predictor rule
allows two or three features, not the 100-plus `LabFeatureExtractor` produces.
So: L2-regularized logistic regression rather than trees, the validated scores
as inputs rather than raw labs, and the baseline scored through the identical
resampling protocol.

**Shipped model: platelet count + AST/ALT ratio.**

| Approach | Features | AUC (bootstrap 95% CI) |
|---|---|---|
| **Model: platelets + AST/ALT** | **2** | **0.943 [0.862–0.994]** |
| Model: all scores + labs | 9 | 0.955 [0.797–1.000] |
| AST/ALT alone | 1 | 0.843 |
| FIB-4 alone | 1 | 0.795 |

Three findings decided the shipped configuration:

1. **The model beats the published score** — 0.94 against 0.80 for FIB-4 alone,
   on the same patients under the same protocol.
2. **Two features match nine.** The point estimates differ by less than the
   noise and the two-feature interval is *narrower*. The extra seven buy
   variance, not signal.
3. **The nine-feature fit gives FIB-4 a negative coefficient** (−1.60) while
   FIB-4 alone is positively associated with cirrhosis. FIB-4 carries platelets
   in its denominator, so once platelet count enters, FIB-4's residual variance
   flips sign. A coefficient contradicting its own univariate direction is a
   collinearity artifact — shipping it would deploy a model whose internals
   argue with the literature it came from.

Platelet count carrying the largest coefficient is the expected result:
thrombocytopenia from portal hypertension is the most reliable single lab
marker of cirrhosis.

**Interval caveat.** Cross-validation folds share training data, so a CI across
them is far too narrow — [0.914–0.951] from folds against [0.797–1.000]
bootstrapped over patients for the same model. `bootstrap_auc_ci` is what gets
reported; the fold interval is kept only to show fold-to-fold stability. With
20 events these results are suggestive, not established.

### Validation on real patients

Scored against ICD-coded phenotypes on 234 MIMIC-IV demo admissions
(`data/gastro_cohort.py`):

| Score | Target | AUC | Median (case / control) |
|---|---|---|---|
| AST/ALT | Cirrhosis | **0.845** | 2.47 / 1.12 |
| FIB-4 | Any liver disease | **0.832** | 6.37 / 1.52 |
| APRI | Any liver disease | 0.814 | 1.93 / 0.34 |
| FIB-4 | Cirrhosis | 0.805 | 6.23 / 1.81 |

18 of 19 coded cirrhosis patients scored FIB-4 above 2.67; none fell below 1.3.

On the same 234 admissions a *trained* deterioration model reaches AUC 0.53.
The published formulae work where learning from this cohort does not — which is
the argument for implementing them rather than fitting them.

Caveats that limit these numbers: ICD codes are billing labels, not adjudicated
diagnoses, and under-code mild disease. n=20 cirrhosis is small. FIB-4
detecting coded cirrhosis is confirmatory of a correct implementation, not a
new finding.

## Scale and tuning

The pipeline was benchmarked at **1,000,000 stays** (26M lab rows, 1.06 GB) in
MIMIC-IV schema, read through the ordinary `MimicIVAdapter` — benchmarking
through a mock would measure the mock.

| | |
|---|---|
| Ingest | 101 s, peak RSS 4.55 GB |
| Train (700k x 81 features) | 35 s, 132 trees after early stopping |
| ROC-AUC | 0.734 |
| Average precision | 0.278 against a 0.115 baseline |
| Brier raw → calibrated | 0.208 → 0.093 |
| Recall at 5% alert budget | 0.198 (precision 0.370) |

Parameters do not transfer across scale. The 1M-tuned defaults
(`min_samples_leaf=50`, early stopping on a 10% split) applied to the 361-stay
page cohort stopped after 25 trees and scored AUC 0.416 — *below chance*. The
page build now selects its regime from the cohort size explicitly.

A sweep over depth 5–12 and 300–800 estimators moved validation AP by under
0.002. At this volume the hyperparameters sit on a plateau and early stopping
decides the tree count regardless; depth 12 cost 40% more time for nothing. The
defaults are set mid-plateau (depth 8, 500 permitted iterations, early stopping
on) rather than at the sweep's nominal winner.

`scripts/generate_scale_cohort.py` writes that cohort. **It is not patient
data.** The achievable AUC is an artifact of the generator — the numbers to
trust from it are throughput and memory.

## Distributed stage placement

`training/placement.py` splits pipeline stages across machines or processes
using rendezvous hashing, which gives the property "random but fixed once
chosen" directly:

- **deterministic** — same seed, stage and worker set, same answer in any
  process on any machine
- **stable under membership change** — removing 1 of 3 workers moved 24% of
  stages in the shipped example, matching its capacity share. Modulo hashing
  (`hash(s) % n`) remaps almost everything when `n` changes.

Placement is derived independently by every participant from the seed and
worker list, so there is no coordinator to fail. Stages that consume the
ingested frame are pinned to it — moving 26M lab rows between machines costs
more than the stage does.

## Status

Verified: data adapters (real MIMIC-III/IV demo cohorts), LOINC harmonization,
clinical NLP, ensemble, calibration, WASM bundle export exact against Python
(1.4e-17 in-browser), Rust scorer (7/7 tests), lab differential, privacy layer,
single-file page.

**The shipped model does not discriminate.** Trained on the pooled MIMIC demo
subsets — 252 training stays — it scores validation AUC 0.530, against 0.5 for
chance. The demo subsets are far too small to learn from; the page says so in a
banner rather than implying competence. Point `MIMIC_AUTOROOTS` at full MIMIC-IV
(~546k stays) and rebuild for a model worth evaluating.

Not built: the FastAPI ingest service and the Python test suite.

Network-blocked in the development environment (org egress policy, HTTP 403):
NCBI E-utilities and Wikipedia. Both clients are written against the documented
APIs but unverified against them. The page's calls run in the *user's* browser
and are unaffected.

---

## Clinical use

This is research software. It is not a medical device, has not been
prospectively validated, and must not be used to make treatment decisions.
