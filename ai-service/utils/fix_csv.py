import csv

FILE = "data/wordpress_normal.csv"
fixed_rows = []

with open(FILE, "r", encoding="utf-8") as f:
    reader = csv.reader(f)
    for row in reader:
        if len(row) == 4:
            row.append("0")
        fixed_rows.append(row)

with open(FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerows(fixed_rows)

print(f"File {FILE} fixato con successo!")
