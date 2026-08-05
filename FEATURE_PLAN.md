# Feature Expansion Plan

## Phase 1: Differential Diagnosis Expansion (All Organ Systems)
**Status:** In Progress

Current: 13 rules (kidney, liver, coagulation, electrolyte, glucose, infection)

### New Rules to Add:

#### Cardiac (6 rules)
- Acute coronary syndrome (elevated troponin, ECG changes)
- Acute heart failure (BNP/NT-proBNP, orthopnea pattern)
- Arrhythmia risk (electrolyte abnormalities: K+, Mg2+, Ca2+)
- Myocarditis (troponin + elevated WBC)
- Pericarditis (troponin + specific pattern)
- Cardiogenic shock (lactate + hypoxia markers)

#### Pulmonary (5 rules)
- Pneumonia (leukocytosis, hypoxia markers)
- Acute respiratory distress syndrome (lactate, organ markers)
- Pulmonary edema (BNP elevation, hypoxia)
- Pulmonary embolism (elevated D-dimer surrogate, hypoxia)
- Acute respiratory failure (pCO2, pH abnormalities in blood gas analogs)

#### Hematology/Coagulation (4 rules - expand current)
- Hemorrhage/bleeding (hemoglobin trend, platelet activation)
- Hemolysis (unconjugated bilirubin spike, LD elevation, Hgb drop)
- Thrombotic thrombocytopenic purpura (severe thrombocytopenia + hemolysis markers)
- Vitamin K deficiency (INR/PT elevation, isolated)

#### Metabolic/Endocrine (4 rules)
- Diabetic ketoacidosis (glucose + pH/bicarbonate pattern)
- Hyperosmolar hyperglycemic state (extreme glucose, osmolality surrogates)
- Thyroid storm (hyperthyroidism signs if TSH available)
- Addisonian crisis (hyponatremia + hyperkalemia pattern)

#### Renal/Hypertension (3 rules - expand AKI)
- Chronic kidney disease (anemia + elevated creatinine baseline pattern)
- Rhabdomyolysis (creatinine spike + myoglobinuria surrogates via LD/CK)
- Glomerulonephritis (proteinuria + hematuria + rising creatinine)

#### Gastrointestinal (3 rules - new)
- Acute liver injury (rapid AST/ALT spike)
- Pancreatitis (lipase/amylase elevation, hypocalcemia)
- Appendicitis/peritonitis (WBC elevation with shift, metabolic acidosis)

**Total new rules: 25 → 38 total**

---

## Phase 2: Additional Hepatology Scoring
**Status:** Planned

### New Scores:
- **Child-Pugh** (3 variables: bilirubin, INR, albumin; 2 clinical: ascites, encephalopathy)
  - Note: Limited without ascites/encephalopathy from labs alone
- **CTP (Child-Turcotte-Pugh)** enhancement (adds disease course staging)
- **FIB-4 interpretation zones** (indeterminate intermediate band)
- **APRI interpretation zones** (fibrosis staging bands)
- **MELD-Na enhancements** (handling edge cases, sodium correction)
- **Forns score** (age, platelet, AST, ALT combination for fibrosis)
- **AST-to-platelet ratio index** refinement
- **Lok score** (for cirrhosis prediction)

**Location:** `features/hepatology.py` (new file)

---

## Phase 3: Standalone Organ-System Models
**Status:** Planned

### Cardiac Risk Model
- Input: troponin, BNP, K+, glucose, lactate, WBC
- Output: MI risk, HF risk, arrhythmia risk (separate scores)
- Training: MIMIC cardiac admissions (ICD codes I10-I52)
- Model: GradientBoosting (same ensemble as deterioration)

### Acute Kidney Injury Progression Model
- Input: creatinine trend, urea, K+, pH, bicarbonate
- Output: AKI stage progression risk (KDIGO staging 1→2→3)
- Training: MIMIC renal codes (ICD N17-N19)
- Model: GradientBoosting

### Sepsis Prediction Model
- Input: WBC, platelets, lactate, creatinine, glucose, temperature surrogate
- Output: Sepsis risk score (0-100)
- Training: MIMIC sepsis admissions (ICD R65.*)
- Model: GradientBoosting

### Pulmonary/Hypoxia Model
- Input: pO2 (if available), lactate, WBC, hemoglobin, creatinine
- Output: Respiratory failure risk
- Training: MIMIC respiratory codes (ICD J80-J96)
- Model: GradientBoosting

**Location:** `models/organ_models.py` (new file)
**Training:** `training/organ_model_trainer.py` (new file)

---

## Phase 4: Real-Time Monitoring
**Status:** Planned

### Drift Detection
- Track model performance over time (AUC, AP on recent data)
- Alert when performance drops >5% from baseline
- Architecture: sliding window (last 100 predictions), baseline (first 1000)

### Alert Thresholds
- Risk bands: Low (<0.1), Moderate (0.1-0.3), High (0.3-0.7), Critical (>0.7)
- Escalation rules: High → notify + recommend urgent review
- Frequency caps: Max 1 alert per patient per hour (alert fatigue)

### Trend Analysis
- Single value vs trajectory over 24/48 hours
- Deterioration velocity (Δ risk / Δ time)
- Anomaly detection (outlier labs vs patient's baseline)

### Performance Monitoring
- Per-site performance (leave-one-site-out evaluation)
- Per-outcome subgroup (sepsis vs AKI vs other)
- Calibration drift (predicted vs observed in buckets)

**Location:** `inference/monitoring.py` (new file)

---

## Phase 5: Lab Result Interpretation - Narrative Generation
**Status:** Planned

### Natural Language Summary
From abnormal labs → readable clinical summary

Examples:
```
"Renal dysfunction: creatinine 2.1 (high) and BUN 52 (marked high) 
suggest acute kidney injury, with concerning metabolic acidosis 
(pH 7.28). Electrolyte derangement: potassium 5.8 (high), sodium 132 (low). 
Risk of cardiac arrhythmias warranting ECG monitoring."
```

### Architecture:
- Rule-based composition (not LLM — stays deterministic and auditable)
- Template system: `{finding} {rationale} {clinical_context}`
- Context rules: prior baseline, trend velocity, organ system interactions

**Location:** `features/narrative_generation.py` (new file)

---

## Implementation Order:
1. ✓ Phase 1A: Add new differential diagnosis rules (1-2 hours)
2. Phase 1B: Validate rules against MIMIC cohort (1 hour)
3. Phase 2: Hepatology scores (1-2 hours)
4. Phase 3: Train organ-system models (2-3 hours)
5. Phase 4: Monitoring infrastructure (2 hours)
6. Phase 5: Narrative generation (1-2 hours)
7. Integration into web interface (1-2 hours)

**Total estimated time: 11-15 hours**

---

## Testing Strategy:
- Unit tests for each new rule/score
- Validation on MIMIC cohorts with known ICD outcomes
- Manual review of generated narratives
- Before/after model performance comparison
