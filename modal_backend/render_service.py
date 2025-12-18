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

# Materials cache to avoid recreation
materials_cache = {{}}

def create_material(name, color, roughness=0.5, metallic=0.0):
    """Create a simple material with the given color."""
    if name in materials_cache:
        return materials_cache[name]
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    materials_cache[name] = mat
    return mat

def create_baseball_field():
    """Create a detailed baseball diamond with grass, dirt, bases, and markings."""
    # Main grass field (pie-wedge shape for baseball)
    bpy.ops.mesh.primitive_circle_add(radius=120, vertices=64, fill_type='NGON', location=(0, 0, 0))
    field = bpy.context.active_object
    field.name = "Field_Grass"
    field.data.materials.append(create_material("Grass", (0.18, 0.42, 0.15), 0.85))

    # Infield grass (inner circle)
    bpy.ops.mesh.primitive_circle_add(radius=29, vertices=48, fill_type='NGON', location=(0, 0, 0.005))
    infield_grass = bpy.context.active_object
    infield_grass.name = "Infield_Grass"
    infield_grass.data.materials.append(create_material("Grass_Infield", (0.2, 0.45, 0.17), 0.85))

    # Infield dirt (full diamond)
    bpy.ops.mesh.primitive_plane_add(size=38, location=(0, 0, 0.01))
    infield = bpy.context.active_object
    infield.rotation_euler = (0, 0, math.radians(45))
    infield.name = "Infield_Dirt"
    infield.data.materials.append(create_material("Dirt", (0.55, 0.38, 0.22), 0.9))

    # Home plate area (larger dirt circle)
    bpy.ops.mesh.primitive_circle_add(radius=8, vertices=32, fill_type='NGON', location=(0, -27, 0.015))
    home_dirt = bpy.context.active_object
    home_dirt.name = "Home_Dirt"
    home_dirt.data.materials.append(create_material("Dirt", (0.55, 0.38, 0.22), 0.9))

    # Pitcher's mound
    bpy.ops.mesh.primitive_uv_sphere_add(radius=2.5, segments=16, ring_count=8, location=(0, 0, 0.3))
    mound = bpy.context.active_object
    mound.scale = (1, 1, 0.15)
    mound.name = "Pitchers_Mound"
    mound.data.materials.append(create_material("Dirt_Mound", (0.52, 0.36, 0.2), 0.9))

    # Pitcher's rubber
    bpy.ops.mesh.primitive_cube_add(size=0.6, location=(0, 0, 0.35))
    rubber = bpy.context.active_object
    rubber.scale = (1, 0.15, 0.05)
    rubber.name = "Pitchers_Rubber"
    rubber.data.materials.append(create_material("White", (0.95, 0.95, 0.95), 0.4))

    # Bases - proper baseball diamond layout
    # Home plate at (0, -27), 1B at (19, -8), 2B at (0, 11), 3B at (-19, -8)
    base_positions = [
        (19, -8, 0.05, "First_Base"),
        (-19, -8, 0.05, "Third_Base"),
        (0, 11, 0.05, "Second_Base"),
    ]
    for x, y, z, name in base_positions:
        bpy.ops.mesh.primitive_plane_add(size=0.38, location=(x, y, z))
        base = bpy.context.active_object
        base.rotation_euler = (0, 0, math.radians(45))
        base.name = name
        base.data.materials.append(create_material("White", (0.98, 0.98, 0.98), 0.3))

    # Home plate (pentagon shape)
    verts = [(0.22, 0, 0.05), (0.22, -0.22, 0.05), (0, -0.35, 0.05),
             (-0.22, -0.22, 0.05), (-0.22, 0, 0.05)]
    faces = [(0, 1, 2, 3, 4)]
    mesh = bpy.data.meshes.new("HomePlate")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    home_plate = bpy.data.objects.new("Home_Plate", mesh)
    home_plate.location = (0, -27, 0)
    bpy.context.collection.objects.link(home_plate)
    home_plate.data.materials.append(create_material("White", (0.98, 0.98, 0.98), 0.3))

    # Batter's boxes
    for x_offset in [-1.2, 1.2]:
        bpy.ops.mesh.primitive_plane_add(size=1, location=(x_offset, -27, 0.02))
        box = bpy.context.active_object
        box.scale = (0.6, 0.9, 1)
        box.name = f"Batters_Box"
        box.data.materials.append(create_material("Dirt_Light", (0.6, 0.45, 0.28), 0.9))

    # Foul lines
    line_mat = create_material("Chalk", (0.98, 0.98, 0.98), 0.7)
    for angle in [45, 135]:
        bpy.ops.mesh.primitive_plane_add(size=1, location=(0, -27, 0.02))
        line = bpy.context.active_object
        line.scale = (0.05, 75, 1)
        line.rotation_euler = (0, 0, math.radians(angle))
        offset_x = 52 * math.cos(math.radians(angle - 90))
        offset_y = 52 * math.sin(math.radians(angle - 90))
        line.location = (offset_x, -27 + offset_y, 0.02)
        line.name = f"Foul_Line_{{angle}}"
        line.data.materials.append(line_mat)

    # Warning track (darker dirt ring in outfield)
    bpy.ops.mesh.primitive_circle_add(radius=115, vertices=64, fill_type='NGON', location=(0, 0, 0.008))
    warning_outer = bpy.context.active_object
    warning_outer.name = "Warning_Track"
    warning_outer.data.materials.append(create_material("Warning_Track", (0.5, 0.35, 0.2), 0.9))

    # Cut out inner grass from warning track
    bpy.ops.mesh.primitive_circle_add(radius=108, vertices=64, fill_type='NGON', location=(0, 0, 0.009))
    grass_inner = bpy.context.active_object
    grass_inner.name = "Outfield_Grass"
    grass_inner.data.materials.append(create_material("Grass", (0.18, 0.42, 0.15), 0.85))

def create_outfield_wall():
    """Create the outfield wall with padding."""
    wall_mat = create_material("Wall_Blue", (0.1, 0.2, 0.4), 0.7)
    padding_mat = create_material("Wall_Padding", (0.15, 0.25, 0.45), 0.85)

    # Create curved outfield wall
    segments = 48
    wall_height = 2.5
    wall_radius = 115

    verts = []
    faces = []

    # Only create wall from left field to right field (arc from -45 to 225 degrees)
    for i in range(segments + 1):
        angle = math.radians(-45 + (270 * i / segments))
        x = wall_radius * math.cos(angle)
        y = wall_radius * math.sin(angle)
        verts.append((x, y, 0))
        verts.append((x, y, wall_height))

    for i in range(segments):
        v1 = i * 2
        v2 = v1 + 1
        v3 = v1 + 3
        v4 = v1 + 2
        faces.append((v1, v2, v3, v4))

    mesh = bpy.data.meshes.new("Outfield_Wall")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    wall = bpy.data.objects.new("Outfield_Wall", mesh)
    bpy.context.collection.objects.link(wall)
    wall.data.materials.append(wall_mat)

    # Wall top (yellow line)
    bpy.ops.mesh.primitive_torus_add(
        major_radius=wall_radius, minor_radius=0.15,
        major_segments=48, minor_segments=8,
        location=(0, 0, wall_height)
    )
    wall_top = bpy.context.active_object
    wall_top.name = "Wall_Top"
    wall_top.data.materials.append(create_material("Yellow", (0.9, 0.8, 0.1), 0.5))

def create_seating_bowl(center_y=-27, tier_name="Lower", inner_r=35, outer_r=55,
                        start_angle=-135, end_angle=135, base_elevation=2,
                        rows=15, row_height=0.55, row_depth=0.8, seat_color=(0.15, 0.25, 0.5)):
    """Create a seating section with visible stepped rows."""
    seat_mat = create_material(f"Seats_{{tier_name}}", seat_color, 0.6)
    concrete_mat = create_material("Concrete", (0.5, 0.48, 0.45), 0.9)

    segments = max(24, int(abs(end_angle - start_angle) / 3))

    verts = []
    faces = []

    for row in range(rows + 1):
        r = inner_r + row * row_depth
        z = base_elevation + row * row_height
        for seg in range(segments + 1):
            angle = math.radians(start_angle + ((end_angle - start_angle) * seg / segments))
            # Offset from home plate
            x = r * math.sin(angle)
            y = center_y - r * math.cos(angle)
            verts.append((x, y, z))

    for row in range(rows):
        for seg in range(segments):
            v1 = row * (segments + 1) + seg
            v2 = v1 + 1
            v3 = v1 + segments + 2
            v4 = v1 + segments + 1
            faces.append((v1, v2, v3, v4))

    mesh = bpy.data.meshes.new(f"Seating_{{tier_name}}")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(f"Seating_{{tier_name}}", mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(seat_mat)

    return obj

def create_stadium_seating():
    """Create the full stadium seating bowl with multiple tiers."""
    # Lower deck - main seating bowl around the infield
    create_seating_bowl(
        tier_name="Lower_Main",
        inner_r=38, outer_r=58,
        start_angle=-120, end_angle=120,
        base_elevation=2, rows=20, row_height=0.5, row_depth=0.85,
        seat_color=(0.12, 0.22, 0.48)
    )

    # Lower deck - down the lines
    create_seating_bowl(
        tier_name="Lower_Left",
        inner_r=40, outer_r=55,
        start_angle=120, end_angle=160,
        base_elevation=1.5, rows=15, row_height=0.5, row_depth=0.85,
        seat_color=(0.12, 0.22, 0.48)
    )
    create_seating_bowl(
        tier_name="Lower_Right",
        inner_r=40, outer_r=55,
        start_angle=-160, end_angle=-120,
        base_elevation=1.5, rows=15, row_height=0.5, row_depth=0.85,
        seat_color=(0.12, 0.22, 0.48)
    )

    # Club level / Mezzanine
    create_seating_bowl(
        tier_name="Club",
        inner_r=60, outer_r=75,
        start_angle=-100, end_angle=100,
        base_elevation=14, rows=12, row_height=0.6, row_depth=0.9,
        seat_color=(0.2, 0.15, 0.35)
    )

    # Upper deck
    create_seating_bowl(
        tier_name="Upper_Main",
        inner_r=65, outer_r=90,
        start_angle=-95, end_angle=95,
        base_elevation=26, rows=22, row_height=0.55, row_depth=0.85,
        seat_color=(0.15, 0.28, 0.52)
    )

    # Outfield bleachers (left)
    create_seating_bowl(
        tier_name="Bleachers_Left",
        inner_r=100, outer_r=118,
        start_angle=135, end_angle=175,
        base_elevation=1, rows=12, row_height=0.5, row_depth=0.9,
        seat_color=(0.15, 0.4, 0.18)
    )

    # Outfield bleachers (right)
    create_seating_bowl(
        tier_name="Bleachers_Right",
        inner_r=100, outer_r=118,
        start_angle=-175, end_angle=-135,
        base_elevation=1, rows=12, row_height=0.5, row_depth=0.9,
        seat_color=(0.15, 0.4, 0.18)
    )

def create_stadium_structure():
    """Create stadium structural elements - concourses, facades, ramps."""
    concrete = create_material("Concrete_Structure", (0.6, 0.58, 0.55), 0.85)
    facade = create_material("Facade", (0.7, 0.68, 0.65), 0.8)

    # Lower concourse (ring behind lower seating)
    bpy.ops.mesh.primitive_cylinder_add(radius=62, depth=4, location=(0, -27, 7), vertices=64)
    lower_con = bpy.context.active_object
    lower_con.name = "Lower_Concourse"
    lower_con.data.materials.append(concrete)

    # Upper concourse
    bpy.ops.mesh.primitive_cylinder_add(radius=78, depth=5, location=(0, -27, 22), vertices=64)
    upper_con = bpy.context.active_object
    upper_con.name = "Upper_Concourse"
    upper_con.data.materials.append(concrete)

    # Stadium back wall / facade
    bpy.ops.mesh.primitive_cylinder_add(radius=95, depth=45, location=(0, -27, 22.5), vertices=64)
    outer = bpy.context.active_object
    bpy.ops.mesh.primitive_cylinder_add(radius=92, depth=50, location=(0, -27, 22.5), vertices=64)
    inner = bpy.context.active_object

    bool_mod = outer.modifiers.new(name="Hollow", type="BOOLEAN")
    bool_mod.operation = "DIFFERENCE"
    bool_mod.object = inner
    bpy.context.view_layer.objects.active = outer
    bpy.ops.object.modifier_apply(modifier="Hollow")
    bpy.data.objects.remove(inner)

    outer.name = "Stadium_Facade"
    outer.data.materials.append(facade)

    # Cut out the outfield opening
    bpy.ops.mesh.primitive_cube_add(size=200, location=(0, 70, 25))
    cut = bpy.context.active_object
    bool_mod = outer.modifiers.new(name="Outfield_Cut", type="BOOLEAN")
    bool_mod.operation = "DIFFERENCE"
    bool_mod.object = cut
    bpy.context.view_layer.objects.active = outer
    bpy.ops.object.modifier_apply(modifier="Outfield_Cut")
    bpy.data.objects.remove(cut)

    # Press box / Luxury suites (behind home plate, upper level)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -85, 35))
    press_box = bpy.context.active_object
    press_box.scale = (30, 8, 6)
    press_box.name = "Press_Box"
    press_box.data.materials.append(create_material("Glass_Dark", (0.1, 0.12, 0.15), 0.1, 0.3))

def create_scoreboard():
    """Create a basic scoreboard in center field."""
    # Main board
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 110, 20))
    board = bpy.context.active_object
    board.scale = (25, 1, 12)
    board.name = "Scoreboard"
    board.data.materials.append(create_material("Scoreboard_Dark", (0.08, 0.08, 0.1), 0.8))

    # Screen (slightly in front)
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 109, 20))
    screen = bpy.context.active_object
    screen.scale = (23, 10, 1)
    screen.rotation_euler = (math.radians(90), 0, 0)
    screen.name = "Scoreboard_Screen"
    screen.data.materials.append(create_material("Screen_Green", (0.1, 0.35, 0.15), 0.3, 0.0))

    # Support structure
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 112, 10))
    support = bpy.context.active_object
    support.scale = (2, 2, 10)
    support.name = "Scoreboard_Support"
    support.data.materials.append(create_material("Steel", (0.4, 0.4, 0.42), 0.4, 0.8))

def create_dugouts():
    """Create dugouts along the first and third base lines."""
    dugout_mat = create_material("Dugout", (0.3, 0.28, 0.25), 0.8)

    for x_mult in [-1, 1]:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x_mult * 25, -22, 0.5))
        dugout = bpy.context.active_object
        dugout.scale = (8, 3, 1.5)
        dugout.name = f"Dugout_{{'' if x_mult > 0 else '3B'}}"
        dugout.data.materials.append(dugout_mat)

        # Dugout roof
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x_mult * 25, -22, 2.2))
        roof = bpy.context.active_object
        roof.scale = (9, 4, 0.3)
        roof.name = f"Dugout_Roof"
        roof.data.materials.append(create_material("Dugout_Roof", (0.25, 0.25, 0.28), 0.7))

def create_foul_poles():
    """Create foul poles at the end of each foul line."""
    pole_mat = create_material("Foul_Pole_Yellow", (0.9, 0.75, 0.1), 0.5, 0.3)

    for angle in [45, 135]:
        x = 115 * math.cos(math.radians(angle - 90))
        y = -27 + 115 * math.sin(math.radians(angle - 90))
        bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=25, location=(x, y, 12.5), vertices=12)
        pole = bpy.context.active_object
        pole.name = f"Foul_Pole_{{angle}}"
        pole.data.materials.append(pole_mat)

def create_light_towers():
    """Create stadium light towers."""
    steel = create_material("Light_Steel", (0.35, 0.35, 0.38), 0.5, 0.7)
    light_mat = create_material("Light_Fixture", (0.9, 0.9, 0.85), 0.2)

    # Light tower positions (around the stadium)
    positions = [
        (75, -80, "Back_Left"),
        (-75, -80, "Back_Right"),
        (85, 20, "Left_Field"),
        (-85, 20, "Right_Field"),
    ]

    for x, y, name in positions:
        # Tower
        bpy.ops.mesh.primitive_cylinder_add(radius=1.5, depth=50, location=(x, y, 25), vertices=8)
        tower = bpy.context.active_object
        tower.name = f"Light_Tower_{{name}}"
        tower.data.materials.append(steel)

        # Light bank
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 52))
        lights = bpy.context.active_object
        lights.scale = (6, 3, 2)
        lights.name = f"Light_Bank_{{name}}"
        lights.data.materials.append(light_mat)

def setup_lighting():
    """Set up realistic stadium lighting."""
    # Main sun (afternoon game lighting)
    bpy.ops.object.light_add(type='SUN', location=(100, -100, 150))
    sun = bpy.context.active_object
    sun.name = "Sun"
    sun.data.energy = 5
    sun.data.color = (1.0, 0.95, 0.9)
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(135))

    # Fill light (opposite side)
    bpy.ops.object.light_add(type='SUN', location=(-80, 50, 100))
    fill = bpy.context.active_object
    fill.name = "Fill_Light"
    fill.data.energy = 1.5
    fill.data.color = (0.9, 0.95, 1.0)
    fill.rotation_euler = (math.radians(60), math.radians(-20), math.radians(-45))

    # Stadium lights (area lights for even illumination)
    for x, y in [(0, -90), (70, -50), (-70, -50), (50, 40), (-50, 40)]:
        bpy.ops.object.light_add(type='AREA', location=(x, y, 60))
        area = bpy.context.active_object
        area.data.energy = 8000
        area.data.size = 15
        area.data.color = (1.0, 0.98, 0.95)
        area.rotation_euler = (math.radians(45), 0, 0)

    # Sky environment
    world = bpy.data.worlds.new("Stadium_World")
    bpy.context.scene.world = world
    world.use_nodes = True

    nodes = world.node_tree.nodes
    links = world.node_tree.links

    # Clear default nodes
    nodes.clear()

    # Create sky texture
    sky = nodes.new('ShaderNodeTexSky')
    sky.sky_type = 'HOSEK_WILKIE'
    sky.sun_elevation = math.radians(45)
    sky.sun_rotation = math.radians(135)
    sky.turbidity = 2.5

    bg = nodes.new('ShaderNodeBackground')
    bg.inputs['Strength'].default_value = 1.0

    output = nodes.new('ShaderNodeOutputWorld')

    links.new(sky.outputs['Color'], bg.inputs['Color'])
    links.new(bg.outputs['Background'], output.inputs['Surface'])

# Load the template
template_path = "/templates/{template_name}"
try:
    bpy.ops.wm.open_mainfile(filepath=template_path)
    print(f"Loaded template: {{template_path}}")
except Exception as e:
    # If template doesn't exist, create procedural stadium
    print(f"Template not found, creating procedural stadium: {{e}}")
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Build the complete stadium
    print("Creating baseball field...")
    create_baseball_field()
    print("Creating outfield wall...")
    create_outfield_wall()
    print("Creating stadium seating...")
    create_stadium_seating()
    print("Creating stadium structure...")
    create_stadium_structure()
    print("Creating scoreboard...")
    create_scoreboard()
    print("Creating dugouts...")
    create_dugouts()
    print("Creating foul poles...")
    create_foul_poles()
    print("Creating light towers...")
    create_light_towers()
    print("Setting up lighting...")
    setup_lighting()
    print("Procedural stadium complete!")

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
