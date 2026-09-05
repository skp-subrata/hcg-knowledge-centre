with open('d:/apps/templates/profile.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'name="interests"' in line:
        print(f"Line {i}: {line.strip()}")
