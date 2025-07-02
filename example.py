import re

# regex to match the date (YYYY-MM-DD) when it's unquoted, capturing the commas around it
date_re = re.compile(r"(,\s*)(\d{4}-\d{2}-\d{2})(\s*,)")

input_path = "ex1.txt"
output_path = "exex.txt"

with open(input_path, "r") as fin, open(output_path, "w") as fout:
    for line in fin:
        # replace , 2024-01-07,  → , '2024-01-07',
        new_line = date_re.sub(r"\1'\2'\3", line)
        fout.write(new_line)
