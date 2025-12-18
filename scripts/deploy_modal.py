#!/usr/bin/env python3
"""Deploy the Modal backend for Blender rendering."""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def main():
    """Deploy the Modal backend."""
    print("Deploying Modal backend...")

    render_service = PROJECT_ROOT / "modal_backend" / "render_service.py"

    if not render_service.exists():
        print(f"Error: render_service.py not found at {render_service}")
        sys.exit(1)

    # Deploy to Modal
    result = subprocess.run(
        ["modal", "deploy", str(render_service)],
        capture_output=True,
        text=True
    )

    print(result.stdout)
    if result.stderr:
        print("Stderr:", result.stderr)

    if result.returncode != 0:
        print("Deployment failed!")
        sys.exit(1)

    print("\nDeployment successful!")
    print("\nNext steps:")
    print("1. Test the backend: python scripts/test_render.py")
    print("2. Run the app: streamlit run app/streamlit_app.py")


if __name__ == "__main__":
    main()
