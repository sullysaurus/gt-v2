"""Service for mapping 2D seatmap coordinates to 3D camera positions."""
import math
from typing import Optional
from pathlib import Path
import yaml

from app.models.venue import Venue, Section
from app.models.camera import CameraPosition
from app.utils.geometry import (
    point_in_polygon,
    polygon_centroid,
    distance_to_polygon_edge,
    calculate_angle_from_center,
)
from app.config import VENUES_DIR


class CoordinateMapper:
    """Maps 2D seatmap click coordinates to 3D camera positions."""

    def __init__(self, venue: Venue):
        self.venue = venue

    @classmethod
    def load_venue(cls, venue_id: str) -> "CoordinateMapper":
        """Load a venue configuration and create a mapper."""
        config_path = VENUES_DIR / venue_id / "config.yaml"

        if not config_path.exists():
            raise FileNotFoundError(f"Venue config not found: {config_path}")

        with open(config_path) as f:
            data = yaml.safe_load(f)

        venue = Venue(**data["venue"])
        return cls(venue)

    def find_section(self, norm_x: float, norm_y: float) -> Optional[Section]:
        """
        Find which section contains the given normalized coordinates.

        Args:
            norm_x: X coordinate normalized to 0-1
            norm_y: Y coordinate normalized to 0-1

        Returns:
            Section if found, None otherwise
        """
        for section in self.venue.sections:
            if point_in_polygon(norm_x, norm_y, section.polygon):
                return section
        return None

    def map_to_camera_position(
        self,
        click_x: int,
        click_y: int,
        image_width: Optional[int] = None,
        image_height: Optional[int] = None,
    ) -> Optional[CameraPosition]:
        """
        Map a click position on the seatmap to a 3D camera position.

        Args:
            click_x: X pixel coordinate of click
            click_y: Y pixel coordinate of click
            image_width: Width of seatmap image (uses config if not provided)
            image_height: Height of seatmap image (uses config if not provided)

        Returns:
            CameraPosition if click is within a section, None otherwise
        """
        # Use configured dimensions if not provided
        width = image_width or self.venue.seatmap.width
        height = image_height or self.venue.seatmap.height

        # Normalize coordinates to 0-1
        norm_x = click_x / width
        norm_y = click_y / height

        # Find the section
        section = self.find_section(norm_x, norm_y)
        if section is None:
            return None

        # Get tier elevation and distance info
        tier = self.venue.get_tier(section.tier)
        if tier is None:
            # Default tier values if not found
            elevation = 10.0
            min_distance, max_distance = 40, 70
        else:
            elevation = tier.elevation
            min_distance, max_distance = tier.distance_range

        # Calculate position within section for row depth
        _, normalized_depth = distance_to_polygon_edge(norm_x, norm_y, section.polygon)

        # Get section center for angle calculation
        section_cx, section_cy = polygon_centroid(section.polygon)

        # Use the section's configured angle, or calculate from position
        if section.angle != 0:
            angle_deg = section.angle
        else:
            # Calculate angle from seatmap center
            angle_deg = calculate_angle_from_center(section_cx, section_cy)

        angle_rad = math.radians(angle_deg)

        # Calculate distance from field center based on row position
        # Front rows (lower normalized_depth) are closer
        distance = min_distance + normalized_depth * (max_distance - min_distance)

        # Calculate 3D position (cylindrical to cartesian)
        # Note: In our coordinate system:
        # - X is left/right
        # - Y is forward/back (toward field)
        # - Z is up/down
        camera_x = distance * math.sin(angle_rad)
        camera_y = -distance * math.cos(angle_rad)  # Negative because behind home plate is -Y
        camera_z = elevation

        # Add slight height variation based on row
        camera_z += normalized_depth * 3  # Rows further back are slightly higher

        # Create camera looking at field center
        target = (
            self.venue.field_center.x,
            self.venue.field_center.y,
            self.venue.field_center.z,
        )

        return CameraPosition.from_position_looking_at(
            position=(camera_x, camera_y, camera_z),
            target=target,
            fov=60.0,
        )

    def get_section_info(self, click_x: int, click_y: int) -> Optional[dict]:
        """Get information about the section at the click position."""
        norm_x = click_x / self.venue.seatmap.width
        norm_y = click_y / self.venue.seatmap.height

        section = self.find_section(norm_x, norm_y)
        if section is None:
            return None

        tier = self.venue.get_tier(section.tier)

        return {
            "section_id": section.id,
            "tier": section.tier,
            "angle": section.angle,
            "elevation": tier.elevation if tier else None,
        }
