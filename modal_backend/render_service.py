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
        "libx11-6",
        "libxi6",
        "libxxf86vm1",
        "libxfixes3",
        "libxrender1",
        "libgl1-mesa-glx",
        "libxkbcommon0",
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

# Load the template
template_path = "/templates/{template_name}"
try:
    bpy.ops.wm.open_mainfile(filepath=template_path)
except Exception as e:
    # If template doesn't exist, create a simple test scene
    print(f"Template not found, creating test scene: {{e}}")
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Create a simple stadium-like scene for testing
    # Ground plane (field)
    bpy.ops.mesh.primitive_plane_add(size=100, location=(0, 0, 0))
    field = bpy.context.active_object
    field.name = "Field"

    # Add green material to field
    mat = bpy.data.materials.new(name="FieldGreen")
    mat.diffuse_color = (0.1, 0.5, 0.1, 1.0)
    field.data.materials.append(mat)

    # Create seating tiers as curved segments
    for tier_num, (elevation, inner_r, outer_r) in enumerate([
        (5, 30, 50),    # Lower tier
        (15, 45, 70),   # Middle tier
        (30, 65, 90),   # Upper tier
    ]):
        # Create a curved segment representing seating
        bpy.ops.mesh.primitive_cylinder_add(
            radius=outer_r,
            depth=10,
            location=(0, 0, elevation)
        )
        outer = bpy.context.active_object

        bpy.ops.mesh.primitive_cylinder_add(
            radius=inner_r,
            depth=12,
            location=(0, 0, elevation)
        )
        inner = bpy.context.active_object

        # Boolean difference to create the ring
        bool_mod = outer.modifiers.new(name="Carve", type="BOOLEAN")
        bool_mod.operation = "DIFFERENCE"
        bool_mod.object = inner
        bpy.context.view_layer.objects.active = outer
        bpy.ops.object.modifier_apply(modifier="Carve")

        # Delete the inner cylinder
        bpy.data.objects.remove(inner)

        outer.name = f"Tier_{{tier_num + 1}}"

        # Add material
        mat = bpy.data.materials.new(name=f"Seats_Tier_{{tier_num + 1}}")
        mat.diffuse_color = (0.3, 0.3, 0.4, 1.0)
        outer.data.materials.append(mat)

    # Add lighting
    bpy.ops.object.light_add(type="SUN", location=(20, 20, 50))
    sun = bpy.context.active_object
    sun.data.energy = 3

    # Add HDRI world lighting
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg_node = world.node_tree.nodes["Background"]
    bg_node.inputs["Color"].default_value = (0.5, 0.7, 1.0, 1.0)

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
