import shutil, os
from pathlib import Path
try:
 import pytesseract
 candidates=[shutil.which("tesseract"),r"C:\Program Files\Tesseract-OCR\tesseract.exe",r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",str(Path.home()/r"AppData\Local\Programs\Tesseract-OCR\tesseract.exe")]
 found=next((p for p in candidates if p and Path(p).exists()),None)
 print("Tesseract:",found or "NAO ENCONTRADO")
 if found:
  pytesseract.pytesseract.tesseract_cmd=found
  print("Versao:",pytesseract.get_tesseract_version())
  print("Idiomas:",", ".join(pytesseract.get_languages(config="")))
except Exception as e: print("Erro:",e)
input("\nPressione ENTER para fechar...")
