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

    def estimate_position_from_click(
        self,
        norm_x: float,
        norm_y: float
    ) -> tuple[float, int, float]:
        """
        Estimate angle, tier, and depth from click position when no section is found.

        Returns:
            Tuple of (angle_degrees, estimated_tier, normalized_depth)
        """
        # Calculate angle from center of seatmap (assumed to be field center)
        angle_deg = calculate_angle_from_center(norm_x, norm_y, 0.5, 0.45)

        # Estimate tier based on distance from center
        # Closer to center = lower tier, further = upper tier
        dist_from_center = math.sqrt((norm_x - 0.5)**2 + (norm_y - 0.45)**2)

        if dist_from_center < 0.25:
            tier = 100  # Lower level
            normalized_depth = dist_from_center / 0.25
        elif dist_from_center < 0.38:
            tier = 200  # Mid level
            normalized_depth = (dist_from_center - 0.25) / 0.13
        else:
            tier = 400  # Upper level
            normalized_depth = min(1.0, (dist_from_center - 0.38) / 0.15)

        return angle_deg, tier, normalized_depth

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
            CameraPosition for the clicked location
        """
        # Use configured dimensions if not provided
        width = image_width or self.venue.seatmap.width
        height = image_height or self.venue.seatmap.height

        # Normalize coordinates to 0-1
        norm_x = click_x / width
        norm_y = click_y / height

        # Find the section
        section = self.find_section(norm_x, norm_y)

        if section is not None:
            # Get tier elevation and distance info
            tier = self.venue.get_tier(section.tier)
            if tier is None:
                elevation = 10.0
                min_distance, max_distance = 40, 70
            else:
                elevation = tier.elevation
                min_distance, max_distance = tier.distance_range

            # Calculate position within section for row depth
            _, normalized_depth = distance_to_polygon_edge(norm_x, norm_y, section.polygon)

            # Use the section's configured angle, or calculate from position
            if section.angle != 0:
                angle_deg = section.angle
            else:
                section_cx, section_cy = polygon_centroid(section.polygon)
                angle_deg = calculate_angle_from_center(section_cx, section_cy)
        else:
            # Fallback: estimate position from click location
            angle_deg, tier_level, normalized_depth = self.estimate_position_from_click(norm_x, norm_y)
            tier = self.venue.get_tier(tier_level)
            if tier is None:
                # Use defaults based on estimated tier
                tier_defaults = {
                    100: (5.0, 30, 55),
                    200: (18.0, 50, 80),
                    400: (38.0, 70, 100),
                }
                elevation, min_distance, max_distance = tier_defaults.get(tier_level, (15.0, 45, 75))
            else:
                elevation = tier.elevation
                min_distance, max_distance = tier.distance_range

        angle_rad = math.radians(angle_deg)

        # Calculate distance from home plate based on row position
        distance = min_distance + normalized_depth * (max_distance - min_distance)

        # Home plate position (seating is arranged around this point)
        # For Yankee Stadium, home plate is at (0, -27, 0)
        home_plate_y = -27

        # Calculate 3D position (cylindrical to cartesian, centered on home plate)
        camera_x = distance * math.sin(angle_rad)
        camera_y = home_plate_y - distance * math.cos(angle_rad)
        camera_z = elevation

        # Add slight height variation based on row
        camera_z += normalized_depth * 3

        # Create camera looking at the field center (pitcher's mound area)
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
