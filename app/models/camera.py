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
        """Create camera position looking at a target point.

        Blender camera coordinate system:
        - Default camera points down -Z axis
        - X rotation (pitch): tilts camera up/down
        - Y rotation (roll): rolls camera left/right
        - Z rotation (yaw): rotates camera horizontally
        """
        px, py, pz = position
        tx, ty, tz = target

        # Calculate direction vector from camera to target
        dx = tx - px
        dy = ty - py
        dz = tz - pz

        # Calculate horizontal distance and total distance
        horizontal_dist = math.sqrt(dx*dx + dy*dy)
        total_dist = math.sqrt(dx*dx + dy*dy + dz*dz)

        if total_dist == 0:
            # Camera at target, return default orientation
            return cls(x=px, y=py, z=pz,
                      rotation=CameraRotation(x=math.pi/2, y=0, z=0),
                      fov=fov)

        # Calculate pitch (X rotation) - how much to look up/down
        # When looking straight ahead, pitch = 90° (π/2)
        # Looking down adds to this, looking up subtracts
        if horizontal_dist > 0:
            pitch_angle = math.atan2(dz, horizontal_dist)
        else:
            pitch_angle = math.pi/2 if dz > 0 else -math.pi/2

        # Blender camera at X=0 points down, X=90° points forward
        rot_x = math.pi/2 - pitch_angle

        # Calculate yaw (Z rotation) - horizontal direction to look
        # atan2(dx, dy) gives angle from +Y axis
        rot_z = math.atan2(dx, dy)

        rotation = CameraRotation(
            x=rot_x,
            y=0,  # No roll
            z=rot_z
        )

        return cls(x=px, y=py, z=pz, rotation=rotation, fov=fov)

    def to_blender_dict(self) -> dict:
        """Convert to dictionary format for Blender API."""
        return {
            "location": (self.x, self.y, self.z),
            "rotation_euler": (self.rotation.x, self.rotation.y, self.rotation.z),
            "fov": self.fov
        }
