#!/usr/bin/env python3
"""Test the coordinate mapping for a venue."""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.coordinate_mapper import CoordinateMapper


def test_mapping(venue_id: str = "yankee_stadium"):
    """Test coordinate mapping for a venue."""
    print(f"Testing coordinate mapping for: {venue_id}")

    try:
        mapper = CoordinateMapper.load_venue(venue_id)
        print(f"Loaded venue: {mapper.venue.name}")
        print(f"Sections defined: {len(mapper.venue.sections)}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Test some sample clicks (normalized to image size)
    test_positions = [
        (640, 720, "Center behind home plate"),
        (450, 600, "Third base side lower"),
        (830, 600, "First base side lower"),
        (640, 850, "Upper deck behind home"),
    ]

    print("\nTesting click positions:")
    print("-" * 60)

    for x, y, description in test_positions:
        print(f"\n{description} ({x}, {y}):")

        section_info = mapper.get_section_info(x, y)
        if section_info:
            print(f"  Section: {section_info['section_id']}")
            print(f"  Tier: {section_info['tier']}")
            print(f"  Angle: {section_info['angle']}°")

            camera = mapper.map_to_camera_position(x, y)
            if camera:
                print(f"  Camera position: ({camera.x:.1f}, {camera.y:.1f}, {camera.z:.1f})")
                print(f"  Camera rotation: ({camera.rotation.x:.2f}, {camera.rotation.y:.2f}, {camera.rotation.z:.2f})")
        else:
            print("  Not in a defined section")


if __name__ == "__main__":
    venue = sys.argv[1] if len(sys.argv) > 1 else "yankee_stadium"
    test_mapping(venue)
