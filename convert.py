import pandas as pd

df = pd.read_csv("DVC_Fall2025_Stats.csv")

df.to_json("DVC_Fall2025_Stats.json", orient="records", indent=2)

print("Conversion complete! JSON file saved as DVC_Fall2025_Stats.json")