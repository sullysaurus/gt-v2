"""Venue and section data models."""
from typing import Optional
from pydantic import BaseModel, Field


class Point2D(BaseModel):
    """2D point with normalized coordinates (0-1)."""
    x: float
    y: float


class Point3D(BaseModel):
    """3D point in meters."""
    x: float
    y: float
    z: float


class SeatmapConfig(BaseModel):
    """Configuration for the seatmap image."""
    file: str
    width: int
    height: int


class Tier(BaseModel):
    """A tier/level in the venue with elevation and distance info."""
    elevation: float = Field(description="Height above field in meters")
    distance_range: tuple[float, float] = Field(
        description="Min/max distance from field center in meters"
    )


class Section(BaseModel):
    """A section in the venue with its 2D polygon and 3D mapping info."""
    id: str
    tier: int = Field(description="Tier level (100, 200, 300, 400)")
    polygon: list[list[float]] = Field(
        description="Polygon vertices as [[x1,y1], [x2,y2], ...] in normalized coords"
    )
    angle: float = Field(
        default=0,
        description="Angle in degrees from center (0 = behind home plate / center ice)"
    )
    row_count: Optional[int] = Field(
        default=None,
        description="Number of rows in this section for finer positioning"
    )


class Venue(BaseModel):
    """Complete venue configuration."""
    id: str
    name: str
    type: str = Field(description="Venue type: baseball, hockey, basketball, football, concert")
    template: str = Field(description="Blender template filename")
    seatmap: SeatmapConfig
    field_center: Point3D = Field(default_factory=lambda: Point3D(x=0, y=0, z=0))
    tiers: dict[int, Tier]
    sections: list[Section]

    def get_section_by_id(self, section_id: str) -> Optional[Section]:
        """Find a section by its ID."""
        for section in self.sections:
            if section.id == section_id:
                return section
        return None

    def get_tier(self, tier_level: int) -> Optional[Tier]:
        """Get tier configuration by level number."""
        return self.tiers.get(tier_level)
