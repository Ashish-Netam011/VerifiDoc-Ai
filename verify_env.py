"""Phase 0 Environment Verification Script"""
import sys

print(f"Python version: {sys.version}")
print(f"Python 3.11+: {sys.version_info >= (3, 11)}")

deps = [
    "fastapi", "uvicorn", "pydantic", "sqlmodel", "pytest",
    "torch", "numpy", "faiss", "rank_bm25",
    "sentence_transformers", "fitz", "pdfplumber",
    "httpx", "rapidfuzz", "dateparser"
]

print("\nDependency checks:")
all_ok = True
for dep in deps:
    try:
        mod = __import__(dep)
        ver = getattr(mod, "__version__", "loaded")
        print(f"  [OK] {dep}: {ver}")
    except ImportError as e:
        print(f"  [FAIL] {dep}: {e}")
        all_ok = False

print(f"\n{'ALL DEPENDENCIES OK' if all_ok else 'SOME DEPENDENCIES FAILED'}")
sys.exit(0 if all_ok else 1)