"""Modal backend for Blender GPU rendering."""
import modal
from pathlib import Path

# Create Modal app
app = modal.App("seat-view-renderer")

# Define the container image with Blender
blender_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "wget",
        "xz-utils",
        # X11 and graphics libraries for Blender
        "libx11-6",
        "libxi6",
        "libxxf86vm1",
        "libxfixes3",
        "libxrender1",
        "libgl1-mesa-glx",
        "libxkbcommon0",
        # Additional required libraries
        "libsm6",          # Session management (was missing!)
        "libice6",         # ICE protocol
        "libxext6",        # X extensions
        "libxrandr2",      # Display size/rotation
        "libglu1-mesa",    # OpenGL utilities
        "libegl1",         # EGL for GPU rendering
        "libgomp1",        # OpenMP for parallel processing
    )
    .run_commands(
        # Download and install Blender 4.2
        "wget -q https://download.blender.org/release/Blender4.2/blender-4.2.0-linux-x64.tar.xz",
        "tar -xf blender-4.2.0-linux-x64.tar.xz -C /opt",
        "rm blender-4.2.0-linux-x64.tar.xz",
        "ln -s /opt/blender-4.2.0-linux-x64/blender /usr/local/bin/blender",
    )
    .pip_install("numpy", "Pillow")
)

# Volume for storing Blender templates
templates_volume = modal.Volume.from_name("venue-templates", create_if_missing=True)


@app.function(
    image=blender_image,
    gpu="L40S",
    timeout=120,
    volumes={"/templates": templates_volume},
)
def render_seat_view(
    venue_id: str,
    template_name: str,
    camera_x: float,
    camera_y: float,
    camera_z: float,
    rotation_x: float,
    rotation_y: float,
    rotation_z: float,
    fov: float = 60.0,
    width: int = 1920,
    height: int = 1080,
    samples: int = 64,
) -> bytes:
    """
    Render a view from a specific camera position in the venue.

    Args:
        venue_id: Venue identifier
        template_name: Name of the Blender template file
        camera_x, camera_y, camera_z: Camera position in meters
        rotation_x, rotation_y, rotation_z: Camera rotation in radians
        fov: Field of view in degrees
        width, height: Render resolution
        samples: Number of render samples

    Returns:
        PNG image data as bytes
    """
    import subprocess
    import tempfile
    import json

    # Create a Python script for Blender to execute
    blender_script = f'''
import bpy
import math
import bmesh

def create_material(name, color, roughness=0.5):
    """Create a simple material with the given color."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat

def create_baseball_field():
    """Create a baseball diamond with grass, dirt, and bases."""
    # Grass outfield (large circle)
    bpy.ops.mesh.primitive_circle_add(radius=95, vertices=64, fill_type='NGON', location=(0, 10, 0))
    outfield = bpy.context.active_object
    outfield.name = "Outfield"
    outfield.data.materials.append(create_material("Grass", (0.15, 0.45, 0.12), 0.8))

    # Infield dirt (diamond shape)
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, -15, 0.01))
    infield = bpy.context.active_object
    infield.rotation_euler = (0, 0, math.radians(45))
    infield.name = "Infield"
    infield.data.materials.append(create_material("Dirt", (0.6, 0.4, 0.25), 0.9))

    # Pitcher's mound
    bpy.ops.mesh.primitive_cylinder_add(radius=3, depth=0.5, location=(0, -15, 0.25))
    mound = bpy.context.active_object
    mound.name = "PitcherMound"
    mound.data.materials.append(create_material("Dirt", (0.55, 0.38, 0.22), 0.9))

    # Home plate area
    bpy.ops.mesh.primitive_circle_add(radius=6, vertices=32, fill_type='NGON', location=(0, -38, 0.01))
    home_area = bpy.context.active_object
    home_area.name = "HomeArea"
    home_area.data.materials.append(create_material("Dirt", (0.6, 0.4, 0.25), 0.9))

    # Bases (white squares)
    base_positions = [(20, 5, 0.1), (-20, 5, 0.1), (0, 28, 0.1), (0, -38, 0.1)]  # 1B, 3B, 2B, Home
    for i, pos in enumerate(base_positions):
        bpy.ops.mesh.primitive_plane_add(size=1.2, location=pos)
        base = bpy.context.active_object
        base.rotation_euler = (0, 0, math.radians(45))
        base.name = f"Base_{{i+1}}"
        base.data.materials.append(create_material("White", (0.95, 0.95, 0.95), 0.3))

    # Foul lines (white lines)
    for angle in [45, 135]:
        bpy.ops.mesh.primitive_plane_add(size=1, location=(0, -38, 0.02))
        line = bpy.context.active_object
        line.scale = (0.15, 60, 1)
        line.rotation_euler = (0, 0, math.radians(angle))
        line.location = (math.cos(math.radians(angle-90)) * 30, -38 + math.sin(math.radians(angle-90)) * 30, 0.02)
        line.name = f"FoulLine_{{angle}}"
        line.data.materials.append(create_material("White", (0.95, 0.95, 0.95), 0.3))

def create_seating_section(inner_radius, outer_radius, start_angle, end_angle, elevation, rows=8, name="Section"):
    """Create a seating section with actual rows of seats."""
    # Create the section as a curved surface
    angle_range = end_angle - start_angle
    segments = max(8, int(abs(angle_range) / 5))

    verts = []
    faces = []

    row_depth = (outer_radius - inner_radius) / rows

    for row in range(rows + 1):
        r = inner_radius + row * row_depth
        z = elevation + row * 0.8  # Each row is 0.8m higher
        for seg in range(segments + 1):
            angle = math.radians(start_angle + (angle_range * seg / segments))
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            verts.append((x, y, z))

    # Create faces
    for row in range(rows):
        for seg in range(segments):
            v1 = row * (segments + 1) + seg
            v2 = v1 + 1
            v3 = v1 + segments + 2
            v4 = v1 + segments + 1
            faces.append((v1, v2, v3, v4))

    # Create mesh
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    return obj

def create_stadium_seating():
    """Create the full stadium seating bowl."""
    seat_material = create_material("Seats_Blue", (0.15, 0.25, 0.45), 0.6)
    seat_material_green = create_material("Seats_Green", (0.2, 0.4, 0.2), 0.6)
    concrete = create_material("Concrete", (0.5, 0.48, 0.45), 0.9)

    # Lower deck - wraps around from left field to right field
    # Behind home plate (main view area)
    for i, (start, end) in enumerate([(-60, -30), (-30, 0), (0, 30), (30, 60)]):
        section = create_seating_section(42, 58, start - 90, end - 90, 3, rows=12, name=f"Lower_{{i}}")
        section.data.materials.append(seat_material)

    # Down the lines
    for start, end in [(-90, -60), (60, 90)]:
        section = create_seating_section(42, 55, start - 90, end - 90, 3, rows=10, name=f"Lower_Line")
        section.data.materials.append(seat_material)

    # Outfield sections
    for start, end in [(-135, -90), (90, 135)]:
        section = create_seating_section(85, 98, start - 90, end - 90, 2, rows=8, name=f"Outfield")
        section.data.materials.append(seat_material_green)

    # Upper deck
    for i, (start, end) in enumerate([(-55, -25), (-25, 5), (5, 35), (35, 65)]):
        section = create_seating_section(60, 82, start - 90, end - 90, 18, rows=15, name=f"Upper_{{i}}")
        section.data.materials.append(seat_material)

    # Create concourse/structure
    bpy.ops.mesh.primitive_cylinder_add(radius=40, depth=3, location=(0, -10, 1.5), vertices=64)
    concourse = bpy.context.active_object
    concourse.name = "Concourse"
    concourse.data.materials.append(concrete)

def create_stadium_structure():
    """Create stadium structural elements."""
    concrete = create_material("Concrete", (0.55, 0.52, 0.48), 0.85)

    # Back wall
    bpy.ops.mesh.primitive_cylinder_add(radius=105, depth=35, location=(0, 0, 17.5), vertices=64)
    outer_wall = bpy.context.active_object

    bpy.ops.mesh.primitive_cylinder_add(radius=100, depth=40, location=(0, 0, 17.5), vertices=64)
    inner_cut = bpy.context.active_object

    bool_mod = outer_wall.modifiers.new(name="Cut", type="BOOLEAN")
    bool_mod.operation = "DIFFERENCE"
    bool_mod.object = inner_cut
    bpy.context.view_layer.objects.active = outer_wall
    bpy.ops.object.modifier_apply(modifier="Cut")
    bpy.data.objects.remove(inner_cut)

    outer_wall.name = "StadiumWall"
    outer_wall.data.materials.append(concrete)

    # Cut out the outfield (open stadium)
    bpy.ops.mesh.primitive_cube_add(size=150, location=(0, 80, 20))
    outfield_cut = bpy.context.active_object

    bool_mod = outer_wall.modifiers.new(name="OpenOutfield", type="BOOLEAN")
    bool_mod.operation = "DIFFERENCE"
    bool_mod.object = outfield_cut
    bpy.context.view_layer.objects.active = outer_wall
    bpy.ops.object.modifier_apply(modifier="OpenOutfield")
    bpy.data.objects.remove(outfield_cut)

def setup_lighting():
    """Set up stadium lighting."""
    # Sun light
    bpy.ops.object.light_add(type='SUN', location=(50, -50, 80))
    sun = bpy.context.active_object
    sun.data.energy = 4
    sun.rotation_euler = (math.radians(45), math.radians(15), math.radians(45))

    # Sky
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]

    # Create a sky gradient
    sky_tex = world.node_tree.nodes.new('ShaderNodeTexGradient')
    mapping = world.node_tree.nodes.new('ShaderNodeMapping')
    tex_coord = world.node_tree.nodes.new('ShaderNodeTexCoord')
    color_ramp = world.node_tree.nodes.new('ShaderNodeValToRGB')

    # Set up gradient from horizon to sky
    color_ramp.color_ramp.elements[0].color = (0.7, 0.8, 0.95, 1)  # Horizon
    color_ramp.color_ramp.elements[1].color = (0.3, 0.5, 0.85, 1)   # Sky

    world.node_tree.links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])
    world.node_tree.links.new(mapping.outputs['Vector'], sky_tex.inputs['Vector'])
    world.node_tree.links.new(sky_tex.outputs['Fac'], color_ramp.inputs['Fac'])
    world.node_tree.links.new(color_ramp.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 1.0

# Load the template
template_path = "/templates/{template_name}"
try:
    bpy.ops.wm.open_mainfile(filepath=template_path)
except Exception as e:
    # If template doesn't exist, create procedural stadium
    print(f"Template not found, creating procedural stadium: {{e}}")
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Build the stadium
    create_baseball_field()
    create_stadium_seating()
    create_stadium_structure()
    setup_lighting()

# Get or create camera
if "Camera" not in bpy.data.objects:
    bpy.ops.object.camera_add()
    camera = bpy.context.active_object
    camera.name = "Camera"
else:
    camera = bpy.data.objects["Camera"]

# Position the camera
camera.location = ({camera_x}, {camera_y}, {camera_z})
camera.rotation_euler = ({rotation_x}, {rotation_y}, {rotation_z})

# Set camera FOV
camera.data.lens_unit = "FOV"
camera.data.angle = math.radians({fov})

# Set as active camera
bpy.context.scene.camera = camera

# Configure render settings
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "GPU"
scene.cycles.samples = {samples}
scene.cycles.use_denoising = True

scene.render.resolution_x = {width}
scene.render.resolution_y = {height}
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"

# Enable GPU compute
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "CUDA"
prefs.get_devices()
for device in prefs.devices:
    device.use = True

# Render
output_path = "/tmp/render_output.png"
scene.render.filepath = output_path
bpy.ops.render.render(write_still=True)

print(f"Render complete: {{output_path}}")
'''

    # Write the script to a temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(blender_script)
        script_path = f.name

    # Run Blender with the script
    result = subprocess.run(
        ["blender", "--background", "--python", script_path],
        capture_output=True,
        text=True
    )

    print("Blender stdout:", result.stdout)
    if result.stderr:
        print("Blender stderr:", result.stderr)

    # Read the rendered image
    output_path = Path("/tmp/render_output.png")
    if output_path.exists():
        return output_path.read_bytes()
    else:
        raise RuntimeError(f"Render failed. Blender output: {result.stdout}\n{result.stderr}")


@app.function(image=blender_image, volumes={"/templates": templates_volume})
def upload_template(template_name: str, template_data: bytes) -> str:
    """Upload a Blender template to the volume."""
    template_path = Path(f"/templates/{template_name}")
    template_path.write_bytes(template_data)
    templates_volume.commit()
    return f"Template uploaded: {template_name}"


@app.function(image=blender_image, volumes={"/templates": templates_volume})
def list_templates() -> list[str]:
    """List all available templates."""
    templates_dir = Path("/templates")
    if templates_dir.exists():
        return [f.name for f in templates_dir.iterdir() if f.suffix == ".blend"]
    return []


# Local entrypoint for testing
@app.local_entrypoint()
def main():
    """Test the render function locally."""
    print("Testing render service...")

    # Test render with a simple camera position
    result = render_seat_view.remote(
        venue_id="test",
        template_name="test.blend",  # Will create test scene if not found
        camera_x=0,
        camera_y=-80,  # Behind home plate position
        camera_z=10,   # Lower tier elevation
        rotation_x=1.57,  # Looking toward field
        rotation_y=0,
        rotation_z=0,
        fov=60,
        width=1280,
        height=720,
        samples=32,
    )

    # Save the result
    output_path = Path("test_render.png")
    output_path.write_bytes(result)
    print(f"Test render saved to: {output_path}")
