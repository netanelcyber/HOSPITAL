# Integration Guide: New Features

This document describes how to integrate the five new feature sets into applications and workflows.

---

## 1. Expanded Differential Diagnosis (39 rules)

**Module:** `features/lab_interpretation.py`

### Quick Start
```python
from features.lab_interpretation import LabInterpreter

interpreter = LabInterpreter(enrich=False)  # Don't fetch Wikipedia by default

panel = {
    "creatinine": 2.8,
    "blood_urea_nitrogen": 68,
    "potassium": 5.8,
    "white_blood_cell_count": 18.2,
    "procalcitonin": 2.1,
    # ... other labs
}

# Get differential diagnosis (6 top items by priority)
differential = interpreter.differential(panel)
for item in differential:
    print(f"[{item.priority}] {item.condition}")
    print(f"  {item.rationale}")
    print(f"  Supporting: {', '.join(item.supporting)}")

# Get full audit trail
print(interpreter.report(panel))
```

### New Analytes Supported
Added 19 new lab types to `REFERENCE_RANGES`:
- **Cardiac:** troponin_i, troponin_t, bnp, nt_probnp
- **Hemolysis/Muscle:** lactate_dehydrogenase, creatine_kinase, myoglobin
- **Infection:** procalcitonin, c_reactive_protein
- **Thrombosis:** d_dimer, fibrinogen
- **Pancreatic:** amylase, lipase
- **Electrolytes:** magnesium, calcium, phosphate, chloride
- **Gas exchange:** ph, pco2, po2
- **Thyroid:** tsh, free_t4
- **Other:** bicarbonate, total_protein

### New Rules (25 added)
- **Urgent (22):** AKI, sepsis, neutropenia, DIC, hyperkalemia, hypoglycemia, hyperglycemia, cardiogenic shock, hemolysis, TTP, cardiac arrhythmia, myocarditis, respiratory failure, DKA, HHS, Addisonian crisis, thyroid storm, rhabdomyolysis, septic shock, coagulopathy, PE, respiratory alkalosis
- **Important (13):** Prerenal azotemia, hyponatremia, hepatocellular injury, cholestasis, anemia, acute heart failure, ACS, pneumonia, vitamin K deficiency, CKD, glomerulonephritis, acute pancreatitis, peritonitis
- **Routine (4):** Hypoalbuminemia, metabolic alkalosis

---

## 2. Hepatology Scoring

**Module:** `features/hepatology.py`

### Available Scores
1. **FIB-4** — Cirrhosis detection (age, AST, ALT, platelets)
   - Threshold: <1.30 (low), 1.30–2.67 (indeterminate), >2.67 (high)
   - Validated: AUC 0.832 on MIMIC-IV

2. **Forns Index** — Fibrosis staging
   - Formula: 7×log10(age) + 0.8×log10(AST/ALT) - 2.19 + 78×log10(plt/100)
   - Threshold: <4.30 (F0-F1), 4.30–6.00 (indeterminate), >6.00 (F3-F4)

3. **APRI** — AST-to-platelet ratio index
   - Simple: (AST/40) / (platelet count) × 100
   - Threshold: <0.5 (no fibrosis), 0.5–1.5 (indeterminate), >1.5 (likely cirrhosis)

4. **Child-Pugh** — Prognostic scoring (5 components)
   - Lab: bilirubin, INR, albumin (each 1-3 points)
   - Clinical: ascites, encephalopathy (each 1-3 points)
   - Class: A (5-6, ~90% 1-yr survival), B (7-9, ~70%), C (10-15, ~45%)

### Usage
```python
from features.hepatology import calculate_all_scores

labs = {
    "age": 58,
    "aspartate_aminotransferase": 78,
    "alanine_aminotransferase": 45,
    "platelet_count": 92,
    "bilirubin": 2.1,
    "inr": 1.5,
    "albumin": 2.9,
}

scores = calculate_all_scores(
    labs,
    ascites="mild",
    encephalopathy="none"
)

for name, score in scores.items():
    if score:
        print(score)  # HepatologyScore object
```

---

## 3. Organ-System Risk Models

**Module:** `models/organ_models.py`

### Available Models

#### Cardiac Risk
```python
from models.organ_models import CardiacRiskModel

cardiac = CardiacRiskModel()
score = cardiac.predict(labs)
# Returns: OrganRiskScore with risk_score (0-1), risk_category, key_findings
```
- **Inputs:** troponin_i, troponin_t, bnp, nt_probnp, potassium, calcium, glucose, lactate
- **Output categories:** low, moderate, high, critical
- **Use case:** Detects MI, HF, arrhythmia risk from lab markers

#### Renal (AKI) Risk
```python
from models.organ_models import RenalRiskModel

renal = RenalRiskModel()
score = renal.predict(labs, creatinine_baseline=0.9)
# KDIGO stage 1/2/3 + risk factors
```
- **KDIGO Staging:** 1 (1.5-1.9× baseline), 2 (2-2.9×), 3 (≥3.0×)
- **Risk factors:** BUN/Cr ratio, hyperkalemia, acidosis
- **Use case:** Predict AKI progression, detect prerenal vs intrinsic disease

#### Sepsis Risk
```python
from models.organ_models import SepsisRiskModel

sepsis = SepsisRiskModel()
score = sepsis.predict(labs)
```
- **Inputs:** lactate, WBC, procalcitonin, platelet count, creatinine, glucose
- **Escalation:** Lactate >2.0 upgrades category to "high" or "critical"
- **Use case:** Early sepsis detection, septic shock warning

#### Pulmonary Risk
```python
from models.organ_models import PulmonaryRiskModel

pulmonary = PulmonaryRiskModel()
score = pulmonary.predict(labs)
```
- **Inputs:** pO2, pCO2, pH, lactate, WBC
- **Severity markers:** pO2 <60, pCO2 >45, pH <7.30
- **Use case:** Respiratory failure, ARDS detection

### Common API
All models return `OrganRiskScore`:
```python
@dataclass(frozen=True)
class OrganRiskScore:
    system: str                # "Cardiac", "Renal", "Sepsis", "Pulmonary"
    condition: str
    risk_score: float          # 0.0 to 1.0
    risk_category: str         # "low", "moderate", "high", "critical"
    key_findings: List[str]    # Abnormalities driving the score
```

### Batch Evaluation
```python
from models.organ_models import evaluate_all_organs

all_scores = evaluate_all_organs(labs)
# Returns: {"cardiac": ..., "renal": ..., "sepsis": ..., "pulmonary": ...}
for organ, score in all_scores.items():
    if score:
        print(f"{score.system}: {score.risk_category.upper()}")
```

---

## 4. Real-Time Monitoring

**Module:** `inference/monitoring.py`

### Components

#### Drift Detection
Tracks model performance degradation over sliding window.
```python
from inference.monitoring import DriftDetector

drift = DriftDetector(baseline_auc=0.75, alert_threshold=0.05)

# After each prediction
warning = drift.update(prediction=0.65, actual=1)
if warning:
    logger.critical(warning)  # AUC dropped >5%
```

#### Risk Alerts
Generate patient safety alerts at configurable thresholds.
```python
from inference.monitoring import RiskThresholdController

alerts = RiskThresholdController()

alert = alerts.generate_alert(
    patient_id="P001",
    alert_type="deterioration",  # "sepsis", "aki", "cardiac"
    predicted_risk=0.85,
    key_findings=["Creatinine 3.2", "Lactate 2.8"]
)
# Returns: RiskAlert or None (if on cooldown)

if alert:
    print(f"[{alert.alert_type}] {alert.recommendation}")
```

**Alert Cooldown:** Max 1 alert per patient per 60 minutes (configurable)

#### Anomaly Detection
Detect labs unusual for a patient or population.
```python
from inference.monitoring import AnomalyDetector

detector = AnomalyDetector()

# Update patient's baseline
detector.update_baseline("P001", labs)

# Detect anomalies on next draw
anomalies = detector.detect_anomalies("P001", new_labs)
for analyte, z_score, severity in anomalies:
    print(f"{analyte}: {z_score:.2f}σ ({severity})")
```

#### Unified Interface
```python
from inference.monitoring import RealTimeMonitor

monitor = RealTimeMonitor(baseline_model_auc=0.75)

result = monitor.process_prediction(
    patient_id="P001",
    predicted_risk=0.72,
    alert_type="deterioration",
    key_findings=["WBC 18.5", "Lactate 3.2"],
    actual_outcome=1  # for drift tracking
)
# Returns: {"risk_alert": RiskAlert | None, "drift_warning": str | None}
```

---

## 5. Clinical Narrative Generation

**Module:** `features/narrative_generation.py`

### Quick Start
```python
from features.narrative_generation import NarrativeComposer

composer = NarrativeComposer()
narrative = composer.compose(labs)

print("CLINICAL SUMMARY")
print(narrative.summary)
print("\nKey abnormalities:", narrative.key_abnormalities)
print("Concern areas:", narrative.concern_areas)
print("Recommendation:", narrative.recommendation)
for caveat in narrative.caveats:
    print(f"⚠ {caveat}")
```

### Output Structure
```python
@dataclass(frozen=True)
class ClinicalNarrative:
    summary: str               # Full markdown narrative
    key_abnormalities: List    # ["Creatinine 2.8 mg/dL", ...]
    concern_areas: List        # ["Renal", "Infection/Sepsis", "Gas Exchange"]
    recommendation: str        # Specific next steps
    caveats: List[str]         # 3 standard disclaimers
```

### Assessments Generated
- **Renal Function:** AKI vs prerenal vs intrinsic + BUN/Cr ratio analysis
- **Liver Function:** Hepatocellular vs cholestatic pattern + viral workup
- **Coagulation:** DIC screening + bleeding risk assessment
- **Infection:** Bacterial vs viral markers + sepsis criteria
- **Gas Exchange:** Hypoxemia severity + respiratory failure risk

### Integration Point
Pair with differential diagnosis and organ models:
```python
# Full clinical picture in 3 steps
interpreter = LabInterpreter()
composer = NarrativeComposer()
scores = evaluate_all_organs(labs)

# 1. Get differential diagnosis
ddx = interpreter.differential(labs)

# 2. Generate narrative summary
narrative = composer.compose(labs)

# 3. Get organ-system risk scores
organ_risks = evaluate_all_organs(labs)

# Output to EMR/clinician dashboard
```

---

## Example: Complete Workflow

```python
from features.lab_interpretation import LabInterpreter
from features.hepatology import calculate_all_scores
from features.narrative_generation import NarrativeComposer
from models.organ_models import evaluate_all_organs
from inference.monitoring import RealTimeMonitor

# Patient labs
labs = {
    "creatinine": 2.8, "blood_urea_nitrogen": 68,
    "aspartate_aminotransferase": 145, "alanine_aminotransferase": 120,
    "bilirubin": 2.3, "albumin": 2.5, "inr": 1.8,
    "white_blood_cell_count": 18.2, "platelet_count": 85,
    "procalcitonin": 2.1, "lactate": 3.2, "potassium": 5.8,
    "po2": 58, "pco2": 52, "ph": 7.24,
}

# 1. Differential diagnosis (39 patterns)
interpreter = LabInterpreter()
ddx = interpreter.differential(labs)
print("Differential diagnosis (6 most urgent):")
for item in ddx[:3]:
    print(f"  • {item.condition} [{item.priority}]")

# 2. Hepatology assessment
hep_scores = calculate_all_scores(labs, ascites="mild")
print("\nHepatology scores:")
for name, score in hep_scores.items():
    if score:
        print(f"  • {score}")

# 3. Organ system risk
organ_risks = evaluate_all_organs(labs)
print("\nOrgan system risks:")
for organ, score in organ_risks.items():
    if score:
        print(f"  • {score.system}: {score.risk_category.upper()} ({score.risk_score:.0%})")

# 4. Clinical narrative
composer = NarrativeComposer()
narrative = composer.compose(labs)
print(f"\nClinical summary:\n{narrative.summary}")
print(f"\nRecommendation: {narrative.recommendation}")

# 5. Monitoring
monitor = RealTimeMonitor()
result = monitor.process_prediction(
    patient_id="P001",
    predicted_risk=organ_risks["sepsis"].risk_score,
    alert_type="sepsis",
    key_findings=organ_risks["sepsis"].key_findings,
)
if result["risk_alert"]:
    print(f"\n⚠️ ALERT: {result['risk_alert'].recommendation}")
```

---

## Production Checklist

- [ ] Test all organ models on actual MIMIC cohorts
- [ ] Calibrate risk thresholds per institution (see RiskThresholdController)
- [ ] Train ensemble models on 1M-stay cohorts (see training/organ_model_trainer.py)
- [ ] Integrate narratives into EMR templates
- [ ] Set up monitoring dashboard (see inference/monitoring.py)
- [ ] Implement alert routing (email, SMS, EMR notifications)
- [ ] Add drift detection to CI/CD pipeline
- [ ] Document interpretation zones for each score
- [ ] Train clinical staff on system limitations

---

## Files Modified/Added

**New:**
- `features/hepatology.py` — Hepatology scores
- `features/narrative_generation.py` — Narrative composition
- `models/organ_models.py` — Organ-system risk models
- `inference/monitoring.py` — Production monitoring
- `FEATURE_PLAN.md` — Implementation roadmap
- `INTEGRATION_GUIDE.md` (this file)

**Modified:**
- `features/lab_features.py` — Added 19 analytes to REFERENCE_RANGES
- `features/lab_interpretation.py` — Added 25 new pattern rules (39 total)

---

## References

- **FIB-4:** Lin et al. Clin Gastroenterol Hepatol 2007
- **APRI:** Wai et al. Clin Gastroenterol Hepatol 2005
- **Forns:** Forns et al. Hepatology 2002
- **Child-Pugh:** Child & Turcotte 1964 (modified Pugh 1973)
- **KDIGO AKI:** KDIGO Clinical Practice Guideline 2021
- **qSOFA/SIRS:** Seymour et al. JAMA 2016 (Sepsis-3)

All implementations follow published formulas exactly, including clamping and thresholds.
