"""Service for building 3D stadium models from seatmap images."""
import json
import base64
from pathlib import Path
from typing import Optional
from openai import OpenAI

from app.config import OPENAI_API_KEY


STADIUM_EXTRACTION_PROMPT = """Analyze this stadium seatmap image and extract the complete 3D structure needed to build a Blender model.

Return a JSON object with this EXACT structure:

{
  "venue_type": "baseball" | "hockey" | "basketball" | "football" | "soccer" | "concert",
  "stadium_shape": "horseshoe" | "oval" | "rectangle" | "circular",

  "field": {
    "type": "baseball_diamond" | "hockey_rink" | "basketball_court" | "football_field" | "soccer_field" | "stage",
    "center_x": 0.5,
    "center_y": 0.45,
    "rotation_degrees": 0,
    "note": "center coordinates as 0-1 normalized, rotation if field is angled"
  },

  "tiers": [
    {
      "level": 100,
      "name": "Field Level / Lower Bowl",
      "elevation_meters": 3,
      "sections": [
        {
          "id": "101",
          "polygon": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],
          "angle_from_home": -60,
          "rows_estimate": 20,
          "is_premium": false
        }
      ]
    },
    {
      "level": 200,
      "name": "Club Level / Mezzanine",
      "elevation_meters": 12,
      "sections": [...]
    },
    {
      "level": 300,
      "name": "Upper Deck",
      "elevation_meters": 25,
      "sections": [...]
    }
  ],

  "special_areas": [
    {
      "type": "bleachers" | "suites" | "press_box" | "scoreboard" | "bullpen",
      "polygon": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],
      "elevation_meters": 5
    }
  ],

  "stadium_dimensions": {
    "outer_radius_estimate": 0.48,
    "inner_radius_estimate": 0.15,
    "note": "as fraction of image width, helps scale the 3D model"
  }
}

CRITICAL INSTRUCTIONS:

1. POLYGONS: Use normalized 0-1 coordinates. (0,0) is top-left, (1,1) is bottom-right.
   Trace the ACTUAL visible boundary of each section as seen in the image.

2. TIERS: Group sections by their elevation level:
   - 100-level (or similarly named): Closest to field, lowest elevation
   - 200-level: Middle tier, club/mezzanine
   - 300/400-level: Upper decks, highest elevation

3. ANGLES: Calculate angle from home plate/center court:
   - 0° = directly behind home plate
   - +90° = first base / right side
   - -90° = third base / left side
   - ±180° = center field / opposite end

4. SECTIONS: Identify EVERY numbered section visible. For baseball stadiums,
   expect 50+ sections per tier. Scan systematically around the stadium.

5. ELEVATION: Estimate realistic heights:
   - Field level: 2-5 meters above field
   - Club level: 10-15 meters
   - Upper deck: 20-35 meters
   - Top level: 35-50 meters

6. ROWS: Estimate number of rows per section based on its depth in the image.

This data will be used to generate accurate Blender 3D geometry, so precision matters."""


class StadiumBuilder:
    """Builds 3D stadium models from seatmap analysis."""

    def __init__(self, api_key: Optional[str] = None):
        self.client = OpenAI(api_key=api_key or OPENAI_API_KEY)

    def _encode_image(self, image_path: Path) -> str:
        """Encode image to base64."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _get_mime_type(self, image_path: Path) -> str:
        """Get MIME type from extension."""
        suffix = image_path.suffix.lower()
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(suffix, "image/png")

    def analyze_seatmap(self, image_path: Path) -> dict:
        """
        Analyze a seatmap and extract complete 3D structure.

        Args:
            image_path: Path to seatmap image

        Returns:
            Dictionary with complete stadium structure
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        base64_image = self._encode_image(image_path)
        mime_type = self._get_mime_type(image_path)

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{base64_image}",
                                    "detail": "high"
                                }
                            },
                            {"type": "text", "text": STADIUM_EXTRACTION_PROMPT}
                        ]
                    }
                ],
                max_tokens=16000,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI API call failed: {str(e)}")

        # Check if we got a valid response
        if not response.choices:
            raise RuntimeError("OpenAI returned no choices in response")

        content = response.choices[0].message.content

        # Check if content is empty
        if not content or not content.strip():
            # Check for refusal or other issues
            finish_reason = response.choices[0].finish_reason
            raise RuntimeError(f"OpenAI returned empty content. Finish reason: {finish_reason}")

        # Strip markdown code blocks if present
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first line (```json or ```)
            lines = lines[1:]
            # Remove last line if it's ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        # Also handle case where it might still have ``` at start
        content = content.strip()
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        # Try to parse JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            # Log first 500 chars for debugging
            preview = content[:500] if content else "(empty)"
            raise RuntimeError(f"Failed to parse OpenAI response as JSON: {e}\nResponse preview: {preview}")

    def generate_blender_script(self, stadium_data: dict, venue_name: str = "Stadium") -> str:
        """
        Generate a Blender Python script to build the stadium.

        Args:
            stadium_data: Structure from analyze_seatmap()
            venue_name: Name for the stadium

        Returns:
            Blender Python script as string
        """
        venue_type = stadium_data.get("venue_type", "baseball")
        field_data = stadium_data.get("field", {})
        tiers = stadium_data.get("tiers", [])
        special_areas = stadium_data.get("special_areas", [])

        # Scale factor: convert normalized coords to meters
        # Assume stadium is roughly 200m across
        scale = 200

        script = f'''
import bpy
import math

# Clear existing objects
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# === MATERIALS ===
def create_material(name, color, roughness=0.5):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat

# Stadium materials
grass_mat = create_material("Grass", (0.15, 0.45, 0.12), 0.85)
dirt_mat = create_material("Dirt", (0.55, 0.38, 0.22), 0.9)
seat_blue = create_material("Seats_Blue", (0.12, 0.22, 0.48), 0.6)
seat_green = create_material("Seats_Green", (0.15, 0.4, 0.18), 0.6)
seat_red = create_material("Seats_Red", (0.5, 0.15, 0.15), 0.6)
concrete = create_material("Concrete", (0.5, 0.48, 0.45), 0.9)
wood = create_material("Wood", (0.4, 0.25, 0.15), 0.8)

# Field center in world coordinates
field_center_x = ({field_data.get('center_x', 0.5)} - 0.5) * {scale}
field_center_y = ({field_data.get('center_y', 0.45)} - 0.5) * {scale}

# === CREATE FIELD ===
'''

        # Add field based on venue type
        if venue_type == "baseball":
            script += '''
# Baseball diamond
bpy.ops.mesh.primitive_circle_add(radius=95, vertices=64, fill_type='NGON', location=(field_center_x, field_center_y, 0))
field = bpy.context.active_object
field.name = "Outfield"
field.data.materials.append(grass_mat)

# Infield dirt
bpy.ops.mesh.primitive_plane_add(size=38, location=(field_center_x, field_center_y - 18, 0.01))
infield = bpy.context.active_object
infield.rotation_euler = (0, 0, math.radians(45))
infield.name = "Infield"
infield.data.materials.append(dirt_mat)

# Home plate area
bpy.ops.mesh.primitive_circle_add(radius=8, vertices=32, fill_type='NGON', location=(field_center_x, field_center_y - 38, 0.02))
home = bpy.context.active_object
home.name = "HomePlateArea"
home.data.materials.append(dirt_mat)

# Pitcher's mound
bpy.ops.mesh.primitive_uv_sphere_add(radius=2.5, location=(field_center_x, field_center_y - 18, 0.3))
mound = bpy.context.active_object
mound.scale = (1, 1, 0.15)
mound.name = "PitchersMound"
mound.data.materials.append(dirt_mat)

# Warning track
bpy.ops.mesh.primitive_torus_add(major_radius=90, minor_radius=5, location=(field_center_x, field_center_y, 0.01))
warning = bpy.context.active_object
warning.scale = (1, 1, 0.01)
warning.name = "WarningTrack"
warning.data.materials.append(dirt_mat)

home_plate_y = field_center_y - 38
'''
        elif venue_type in ["hockey", "basketball"]:
            script += '''
# Indoor court/rink
bpy.ops.mesh.primitive_plane_add(size=60, location=(field_center_x, field_center_y, 0))
court = bpy.context.active_object
court.scale = (1.5, 1, 1)
court.name = "Court"
court.data.materials.append(wood if venue_type == "basketball" else create_material("Ice", (0.9, 0.95, 1.0), 0.1))

home_plate_y = field_center_y - 30
'''
        else:
            script += '''
# Generic field
bpy.ops.mesh.primitive_plane_add(size=100, location=(field_center_x, field_center_y, 0))
field = bpy.context.active_object
field.name = "Field"
field.data.materials.append(grass_mat)

home_plate_y = field_center_y - 50
'''

        # Add seating sections from each tier
        script += '''

# === CREATE SEATING SECTIONS ===
def create_section_geometry(polygon_normalized, elevation, rows, name, material):
    """Create a seating section from normalized polygon coordinates."""
    scale = ''' + str(scale) + '''

    # Convert normalized coords to world coords
    points = []
    for px, py in polygon_normalized:
        wx = (px - 0.5) * scale
        wy = (py - 0.5) * scale
        points.append((wx, wy))

    if len(points) < 3:
        return None

    # Create mesh for seating section
    verts = []
    faces = []

    row_height = 0.5
    row_depth = 0.8

    # Create stepped rows
    for row in range(rows):
        z = elevation + row * row_height
        # Interpolate between inner and outer edge
        t = row / max(rows - 1, 1)

        for i, (x, y) in enumerate(points):
            # Offset each row slightly outward
            cx = sum(p[0] for p in points) / len(points)
            cy = sum(p[1] for p in points) / len(points)
            dx = x - cx
            dy = y - cy

            verts.append((
                x + dx * t * 0.3,
                y + dy * t * 0.3,
                z
            ))

    # Create faces connecting rows
    n_points = len(points)
    for row in range(rows - 1):
        for i in range(n_points):
            v1 = row * n_points + i
            v2 = row * n_points + (i + 1) % n_points
            v3 = (row + 1) * n_points + (i + 1) % n_points
            v4 = (row + 1) * n_points + i
            faces.append((v1, v2, v3, v4))

    # Top face
    top_start = (rows - 1) * n_points
    faces.append(tuple(range(top_start, top_start + n_points)))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)

    return obj

# Seat colors by tier
tier_materials = {
    100: seat_blue,
    200: seat_red,
    300: seat_green,
    400: seat_blue,
}

'''

        # Add each tier's sections
        for tier in tiers:
            level = tier.get("level", 100)
            elevation = tier.get("elevation_meters", 5)
            sections = tier.get("sections", [])

            script += f'''
# === TIER {level}: {tier.get("name", "Unknown")} ===
'''
            for section in sections:
                section_id = section.get("id", "unknown")
                polygon = section.get("polygon", [])
                rows = section.get("rows_estimate", 15)

                if len(polygon) >= 3:
                    script += f'''
create_section_geometry(
    {polygon},
    {elevation},
    {rows},
    "Section_{section_id}",
    tier_materials.get({level}, seat_blue)
)
'''

        # Add lighting and sky
        script += '''

# === LIGHTING ===
# Sun
bpy.ops.object.light_add(type='SUN', location=(50, -50, 100))
sun = bpy.context.active_object
sun.data.energy = 5
sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(45))

# Fill light
bpy.ops.object.light_add(type='SUN', location=(-50, 50, 80))
fill = bpy.context.active_object
fill.data.energy = 2
fill.rotation_euler = (math.radians(60), math.radians(-20), math.radians(-45))

# Area lights for stadium lighting
for x, y in [(0, -80), (60, -40), (-60, -40), (40, 40), (-40, 40)]:
    bpy.ops.object.light_add(type='AREA', location=(x, y, 50))
    area = bpy.context.active_object
    area.data.energy = 5000
    area.data.size = 20

# Sky
world = bpy.data.worlds.new("Stadium_World")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.4, 0.6, 0.9, 1.0)
bg.inputs["Strength"].default_value = 1.0

# === STADIUM STRUCTURE ===
# Outer wall
bpy.ops.mesh.primitive_cylinder_add(radius=110, depth=40, location=(field_center_x, field_center_y, 20), vertices=64)
outer = bpy.context.active_object
bpy.ops.mesh.primitive_cylinder_add(radius=105, depth=45, location=(field_center_x, field_center_y, 20), vertices=64)
inner = bpy.context.active_object

mod = outer.modifiers.new("Bool", "BOOLEAN")
mod.operation = "DIFFERENCE"
mod.object = inner
bpy.context.view_layer.objects.active = outer
bpy.ops.object.modifier_apply(modifier="Bool")
bpy.data.objects.remove(inner)

outer.name = "StadiumShell"
outer.data.materials.append(concrete)

print("Stadium generation complete!")
'''

        return script

    def save_blender_script(self, stadium_data: dict, output_path: Path, venue_name: str = "Stadium"):
        """Save the Blender script to a file."""
        script = self.generate_blender_script(stadium_data, venue_name)
        output_path = Path(output_path)
        output_path.write_text(script)
        return output_path
