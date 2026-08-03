import sys, json, numpy as np, pandas as pd, logging
sys.path.insert(0,"/home/user/HOSPITAL"); logging.basicConfig(level=logging.ERROR)
rng = np.random.default_rng(0); n=3000
labs={"glucose":rng.normal(110,35,n),"hemoglobin":rng.normal(13,2,n),"potassium":rng.normal(4,.6,n),
      "sodium":rng.normal(138,5,n),"creatinine":rng.lognormal(0,.5,n),
      "platelet_count":rng.normal(250,70,n),"white_blood_cell_count":rng.normal(8,4,n)}
logit=-2.5+1.1*np.log(labs["creatinine"])+0.05*(labs["white_blood_cell_count"]-8)-0.004*(labs["platelet_count"]-250)
y=rng.binomial(1,1/(1+np.exp(-logit)))
agree=rng.random(n)<0.65; sick=np.where(agree,y==1,y==0)
notes=np.where(sick,"Assessment: severe sepsis, hypotensive on norepinephrine.",
                    "Assessment: stable, afebrile, improving. No evidence of sepsis.")
c=pd.DataFrame({"patient_id":[f"P{i}" for i in range(n)],"deteriorated":y,"medical_report":notes})
for k,v in labs.items(): c[f"lab_{k}"]=v
from training.pipeline import TrainingPipeline
from inference.wasm_export import export_bundle
p=TrainingPipeline(); r=p.train(c)
b=export_bundle(r.ensemble,r.lab_extractor,r.calibrator,output_path="wasm/tests/fixture_bundle.json")
X=p.build_features(c.head(200),fit=False)
# Inject NaNs so the missing-value branch is exercised, not just dodged.
Xn=X.to_numpy().copy(); Xn[rng.random(Xn.shape)<0.1]=np.nan
scores=r.calibrator.transform(r.ensemble.predict_proba(pd.DataFrame(Xn,columns=X.columns)))
json.dump({"features":[[None if np.isnan(v) else v for v in row] for row in Xn.tolist()],
           "expected":scores.tolist()},open("wasm/tests/fixture_cases.json","w"))
print("fixture rows:",len(scores),"features:",Xn.shape[1])
