#!/usr/bin/env python3
"""Test the Modal render backend."""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import modal


def test_render():
    """Test a basic render through Modal."""
    print("Testing Modal render backend...")

    # Look up the deployed function
    try:
        render_fn = modal.Function.lookup("seat-view-renderer", "render_seat_view")
    except modal.exception.NotFoundError:
        print("Error: Modal function not found. Deploy first with:")
        print("  modal deploy modal_backend/render_service.py")
        sys.exit(1)

    print("Calling render function...")

    # Test render with default test scene
    image_data = render_fn.remote(
        venue_id="test",
        template_name="test.blend",  # Will create test scene
        camera_x=0,
        camera_y=-60,
        camera_z=15,
        rotation_x=1.4,
        rotation_y=0,
        rotation_z=0,
        fov=60,
        width=1280,
        height=720,
        samples=32,
    )

    # Save output
    output_path = PROJECT_ROOT / "test_render_output.png"
    output_path.write_bytes(image_data)
    print(f"Test render saved to: {output_path}")
    print(f"Image size: {len(image_data)} bytes")
    print("\nSuccess! The Modal backend is working.")


if __name__ == "__main__":
    test_render()
