# Patient Deterioration Prediction System

תוכנה לחיזוי התדרדרות מצב של מטופלים על בסיס בדיקות מעבדה עם שימוש בדוחות רפואיים כמידע סיוע.

##개요 (Overview)

מערכת ML לחיזוי התדרדרות מצב מטופלים באמצעות:
- **Primary Feature**: תוצאות בדיקות מעבדה (חומצות חיזור, אלקטרוליטים, נוספים)
- **Auxiliary Data**: דוחות רפואיים (הערות קליניות, היסטוריה רפואית)

## תיקייה הבנייה (Project Structure)

```
HOSPITAL/
├── data/                          # ניהול נתונים
│   ├── raw/                       # נתונים גולמיים
│   ├── processed/                 # נתונים מעובדים
│   └── loaders.py                 # טוענות נתונים
├── features/                      # הנדסת תכונות
│   ├── lab_features.py            # תכונות בדיקות מעבדה
│   └── clinical_features.py       # תכונות מדוחות קליניים
├── models/                        # מודלי ML
│   ├── ensemble.py                # מודל אנסמבל
│   ├── gradient_boosting.py       # Gradient Boosting
│   └── calibration.py             # כיול הסתברויות
├── training/                      # הדרכה
│   ├── pipeline.py                # צינור הדרכה
│   ├── validation.py              # ולידציה וערכון
│   └── hyperparameter_tuning.py   # כיוונון פרמטרים
├── inference/                     # הסקה
│   ├── predictor.py               # מנבא הסקה
│   └── explainer.py               # הסברים (SHAP)
├── api/                           # API ווב
│   ├── app.py                     # אפליקציית FastAPI
│   └── schemas.py                 # סכימות הנתונים
├── tests/                         # בדיקות
│   ├── test_features.py
│   ├── test_models.py
│   └── test_api.py
├── notebooks/                     # ניוטבוק למחקר
│   └── exploratory_analysis.ipynb
├── requirements.txt               # תלויות
├── config.yaml                    # הגדרות
└── README.md                      # זה הקובץ

```

## התקנה (Installation)

```bash
pip install -r requirements.txt
```

## שימוש (Usage)

### הדרכה
```python
from training.pipeline import TrainingPipeline

pipeline = TrainingPipeline(config_path='config.yaml')
pipeline.train()
```

### חיזוי
```python
from inference.predictor import PatientDeteriorationPredictor

predictor = PatientDeteriorationPredictor(model_path='models/best_model.pkl')
risk_score = predictor.predict(lab_tests, medical_report)
```

### API
```bash
python api/app.py
```

ייגש ל-http://localhost:8000/docs לתיעוד API

## תכונות עיקריות

- ✅ חיזוי כושר על בסיס בדיקות מעבדה בלבד
- ✅ שימוש בדוחות רפואיים כמידע סיוע
- ✅ הסברות מנבא (SHAP)
- ✅ API REST למודל
- ✅ ולידציה כלונית ובדיקות
- ✅ כיול הסתברויות
- ✅ ניהול מודלים וורסיוני

## דרישות

- Python 3.9+
- scikit-learn
- xgboost
- shap
- fastapi
- pydantic
- pandas
- numpy

## מחבר

Hospital ML Team
