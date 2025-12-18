"""Camera position and rotation models."""
import math
from pydantic import BaseModel, Field


class CameraRotation(BaseModel):
    """Camera rotation in Euler angles (radians)."""
    x: float = Field(description="Pitch - rotation around X axis")
    y: float = Field(description="Yaw - rotation around Y axis")
    z: float = Field(description="Roll - rotation around Z axis")


class CameraPosition(BaseModel):
    """Complete camera position and orientation for Blender rendering."""
    x: float = Field(description="X position in meters")
    y: float = Field(description="Y position in meters")
    z: float = Field(description="Z position in meters (elevation)")
    rotation: CameraRotation
    fov: float = Field(default=60.0, description="Field of view in degrees")

    @classmethod
    def from_position_looking_at(
        cls,
        position: tuple[float, float, float],
        target: tuple[float, float, float],
        fov: float = 60.0
    ) -> "CameraPosition":
        """Create camera position looking at a target point."""
        px, py, pz = position
        tx, ty, tz = target

        # Calculate direction vector
        dx = tx - px
        dy = ty - py
        dz = tz - pz

        # Normalize
        length = math.sqrt(dx*dx + dy*dy + dz*dz)
        if length > 0:
            dx /= length
            dy /= length
            dz /= length

        # Calculate Euler angles
        # Pitch: angle looking up/down
        pitch = math.asin(-dz)

        # Yaw: angle looking left/right
        yaw = math.atan2(dx, dy)

        # Roll: keep camera level
        roll = 0.0

        # Blender uses a different rotation order, adjust for that
        # Converting to Blender's XYZ Euler rotation
        rotation = CameraRotation(
            x=pitch + math.pi/2,  # Blender camera default points down -Z
            y=0,
            z=yaw + math.pi
        )

        return cls(x=px, y=py, z=pz, rotation=rotation, fov=fov)

    def to_blender_dict(self) -> dict:
        """Convert to dictionary format for Blender API."""
        return {
            "location": (self.x, self.y, self.z),
            "rotation_euler": (self.rotation.x, self.rotation.y, self.rotation.z),
            "fov": self.fov
        }
