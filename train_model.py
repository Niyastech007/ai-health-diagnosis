import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.utils import resample
from sklearn.model_selection import train_test_split
import joblib

df = pd.read_csv("health_dataset_10000_accurate.csv")
df.dropna(inplace=True)

df["ChestPain"] = df["ChestPain"].map({"Yes":1,"No":0})

min_count = df["Disease"].value_counts().min()
balanced_data = []

for disease in df["Disease"].unique():
    df_d = df[df["Disease"] == disease]
    df_d_resampled = resample(df_d, replace=False,
                              n_samples=min_count,
                              random_state=42)
    balanced_data.append(df_d_resampled)

df_balanced = pd.concat(balanced_data)

X = df_balanced[["Age","TopBP","BottomBP","Sugar","BMI","ChestPain"]]
y = df_balanced["Disease"]

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

model = RandomForestClassifier(n_estimators=300, random_state=42)
model.fit(X_scaled,y)

joblib.dump(model,"model.pkl")
joblib.dump(scaler,"scaler.pkl")

print("Model & Scaler saved")