import sys
sys.path.insert(0, ".")

from app.main import app

print("=" * 60)
print("FastAPI app created OK!")
print("=" * 60)
print(f"\nTitle: {app.title}")
print(f"Version: {app.version}")
print(f"\nRoutes ({len(app.routes)} total):")
print("-" * 60)

for route in app.routes:
    if hasattr(route, "path"):
        methods = getattr(route, "methods", None)
        method_str = ",".join(sorted(methods)) if methods else "ALL"
        print(f"  {method_str:<20} {route.path}")

print("-" * 60)
print("\nAll imports successful! Step 11 API layer is ready.")
