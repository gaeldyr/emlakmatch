import os

# Alınacak dosya uzantıları
TARGET_EXTS = ('.py', '.html', '.sql')

# Taranmayacak klasörler
IGNORE_DIRS = {'.venv', 'venv', 'env', '__pycache__', '.git', '.vscode', 'node_modules', 'static'}

output_filename = "project_dump.txt"

with open(output_filename, "w", encoding="utf-8") as outfile:
    for root, dirs, files in os.walk("."):
        # Yoksayılacak klasörleri filtrele
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            if file.endswith(TARGET_EXTS) and file != output_filename and file != "dump.py":
                file_path = os.path.join(root, file)
                outfile.write(f"\n\n{'='*70}\n")
                outfile.write(f"FILE: {file_path}\n")
                outfile.write(f"{'='*70}\n\n")
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as infile:
                        outfile.write(infile.read())
                except Exception as e:
                    outfile.write(f"[HATA OKUNAMADI: {e}]\n")

print(f"Bitti! '{output_filename}' başarıyla oluşturuldu.")