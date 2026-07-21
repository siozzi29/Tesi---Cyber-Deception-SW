import pandas as pd
df = pd.read_csv("ai-service/data/csic_ecml_final.csv", dtype=str, keep_default_na=False)
print(df["Class"].value_counts())