import json

with open("brands_config.json", "rb") as f:
    data = f.read()

print(data[:300])