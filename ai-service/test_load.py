import joblib

model = joblib.load("models/isolation_forest.joblib")
scaler = joblib.load("models/scaler.joblib")
features = joblib.load("models/feature_order.joblib")

print("Modello caricato:", model)
print("Numero feature attese:", len(features))
print("Feature:", features)