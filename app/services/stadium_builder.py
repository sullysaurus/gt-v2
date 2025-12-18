"""Service for building 3D stadium models from seatmap images."""
import json
import base64
from pathlib import Path
from typing import Optional
from openai import OpenAI

from app.config import OPENAI_API_KEY


STADIUM_EXTRACTION_PROMPT = """Analyze this stadium seatmap image and extract the 3D structure for a Blender model.

Return a JSON object with this structure:

{
  "venue_type": "baseball" | "hockey" | "basketball" | "football" | "soccer" | "concert",
  "stadium_shape": "horseshoe" | "oval" | "rectangle" | "circular",
  "field": {
    "type": "hockey_rink" | "baseball_diamond" | "basketball_court" | "football_field" | "stage",
    "center_x": 0.5,
    "center_y": 0.5
  },
  "tiers": [
    {
      "level": 100,
      "name": "Lower Bowl",
      "elevation_meters": 5,
      "inner_radius": 0.15,
      "outer_radius": 0.35,
      "start_angle": -180,
      "end_angle": 180
    }
  ],
  "stadium_dimensions": {
    "outer_radius": 0.48,
    "inner_radius": 0.12
  }
}

INSTRUCTIONS:
1. Identify the venue type and shape from the image
2. Locate the field/court center (0-1 normalized, 0,0 = top-left)
3. For each seating tier visible (100-level, 200-level, 300-level, etc):
   - Estimate elevation in meters (lower=5m, club=12m, upper=25m, top=40m)
   - Estimate inner and outer radius as fraction of image (0-1)
   - Estimate angular coverage (start_angle to end_angle, 0=bottom center)
4. Provide overall stadium dimensions

Keep response concise. Only include tiers that are clearly visible."""


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

        # Read and encode image
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        if len(image_bytes) < 1000:
            raise RuntimeError(f"Image file too small ({len(image_bytes)} bytes), may be corrupted")

        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        mime_type = self._get_mime_type(image_path)

        # Log image size for debugging
        print(f"Image size: {len(image_bytes)} bytes, base64 length: {len(base64_image)}")

        # Build the image URL
        image_url = f"data:{mime_type};base64,{base64_image}"

        # Try latest vision models in order of preference
        models_to_try = ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini"]
        last_error = None

        for model in models_to_try:
            try:
                print(f"Trying model: {model}")
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": image_url,
                                        "detail": "high"
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": "Analyze this stadium seatmap image and return a JSON object. " + STADIUM_EXTRACTION_PROMPT
                                }
                            ]
                        }
                    ],
                    max_tokens=16000,
                )

                # Check if the response indicates vision failure
                content = response.choices[0].message.content if response.choices else ""
                if "unable to analyze" in content.lower() or "cannot see" in content.lower():
                    print(f"Model {model} couldn't see the image, trying next...")
                    last_error = RuntimeError(f"Model {model} could not process the image")
                    continue

                # Success - break out of loop
                break

            except Exception as e:
                print(f"Model {model} failed: {str(e)}")
                last_error = e
                continue
        else:
            # All models failed
            raise RuntimeError(f"All vision models failed. Last error: {str(last_error)}")

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

        # Try to parse JSON, with repair for truncated responses
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            # Try to repair truncated JSON
            repaired = self._repair_truncated_json(content)
            if repaired:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

            # Log first 500 chars for debugging
            preview = content[:500] if content else "(empty)"
            raise RuntimeError(f"Failed to parse OpenAI response as JSON: {e}\nResponse preview: {preview}")

    def _repair_truncated_json(self, content: str) -> Optional[str]:
        """Attempt to repair truncated JSON by closing open brackets."""
        if not content:
            return None

        # Count open brackets
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')

        # If we have unclosed structures, try to close them
        if open_braces > 0 or open_brackets > 0:
            # Find the last complete structure
            # Remove any partial content after the last comma or complete value
            lines = content.rstrip().split('\n')

            # Remove the last line if it looks truncated
            while lines:
                last_line = lines[-1].strip()
                # Check if last line is incomplete (doesn't end with valid JSON ending)
                if last_line and not last_line.endswith((',', '{', '[', '}', ']', '"', 'true', 'false', 'null')) and not last_line[-1].isdigit():
                    lines.pop()
                else:
                    break

            content = '\n'.join(lines)

            # Now close all open brackets/braces
            # First close any open arrays, then objects
            for _ in range(open_brackets):
                content += ']'
            for _ in range(open_braces):
                content += '}'

            # Clean up any trailing commas before closing brackets
            content = content.replace(',]', ']').replace(',}', '}')

            return content

        return None

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

        # Add seating tiers using arc geometry
        script += '''

# === CREATE SEATING TIERS ===
def create_seating_tier(inner_r, outer_r, start_ang, end_ang, elevation, rows, name, material):
    """Create a seating tier as an arc with stepped rows."""
    verts = []
    faces = []

    segments = 32  # Number of segments around the arc
    row_height = 0.5

    # Convert angles to radians
    start_rad = math.radians(start_ang - 90)  # Offset so 0 = bottom
    end_rad = math.radians(end_ang - 90)

    for row in range(rows):
        z = elevation + row * row_height
        # Interpolate radius from inner to outer
        t = row / max(rows - 1, 1)
        r = inner_r + (outer_r - inner_r) * t

        for i in range(segments + 1):
            angle = start_rad + (end_rad - start_rad) * (i / segments)
            x = r * math.cos(angle) + field_center_x
            y = r * math.sin(angle) + field_center_y
            verts.append((x, y, z))

    # Create faces between rows
    pts_per_row = segments + 1
    for row in range(rows - 1):
        for i in range(segments):
            v1 = row * pts_per_row + i
            v2 = row * pts_per_row + i + 1
            v3 = (row + 1) * pts_per_row + i + 1
            v4 = (row + 1) * pts_per_row + i
            faces.append((v1, v2, v3, v4))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj

# Seat colors by tier level
tier_materials = {
    100: seat_blue,
    200: seat_red,
    300: seat_green,
    400: seat_blue,
}

scale = ''' + str(scale) + '''

'''

        # Add each tier
        for tier in tiers:
            level = tier.get("level", 100)
            elevation = tier.get("elevation_meters", 5)
            inner_r = tier.get("inner_radius", 0.15) * scale
            outer_r = tier.get("outer_radius", 0.35) * scale
            start_ang = tier.get("start_angle", -180)
            end_ang = tier.get("end_angle", 180)
            rows = max(5, int((outer_r - inner_r) / 2))  # Estimate rows from depth
            name = tier.get("name", f"Tier_{level}")

            script += f'''
# === TIER {level}: {name} ===
create_seating_tier(
    {inner_r}, {outer_r},
    {start_ang}, {end_ang},
    {elevation}, {rows},
    "{name}",
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
