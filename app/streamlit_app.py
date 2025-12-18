"""Streamlit app for seat view visualization."""
import streamlit as st
from PIL import Image
from pathlib import Path
import io
import sys
import yaml

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.coordinate_mapper import CoordinateMapper
from app.services.render_client import RenderClient
from app.config import VENUES_DIR, DATA_DIR, OPENAI_API_KEY


def analyze_seatmap_with_ai(venue_id: str) -> dict:
    """Use OpenAI Vision to analyze the seatmap and detect sections."""
    from app.services.openai_analyzer import SeatmapAnalyzer

    seatmap_path = VENUES_DIR / venue_id / "seatmap.png"
    if not seatmap_path.exists():
        raise FileNotFoundError(f"Seatmap not found: {seatmap_path}")

    analyzer = SeatmapAnalyzer()
    return analyzer.analyze(seatmap_path)


def update_venue_config_with_ai_sections(venue_id: str, analysis: dict) -> int:
    """Update venue config with AI-detected sections."""
    config_path = VENUES_DIR / venue_id / "config.yaml"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Update sections from AI analysis
    new_sections = []
    for section in analysis.get("sections", []):
        new_sections.append({
            "id": str(section.get("id", "")),
            "tier": section.get("tier", 100),
            "polygon": section.get("approximate_polygon", []),
            "angle": section.get("angle_from_center", 0),
        })

    # Merge with existing sections (AI sections take precedence by ID)
    existing_ids = {s["id"] for s in new_sections}
    for existing in config["venue"].get("sections", []):
        if existing["id"] not in existing_ids:
            new_sections.append(existing)

    config["venue"]["sections"] = new_sections

    # Update tiers if detected
    if "tiers" in analysis:
        elevation_map = {"low": 5.0, "medium": 15.0, "high": 28.0, "very_high": 40.0}
        distance_map = {"low": (25, 50), "medium": (45, 70), "high": (60, 85), "very_high": (75, 100)}

        for tier in analysis["tiers"]:
            level = tier.get("level", 100)
            elevation = tier.get("relative_elevation", "low")
            if level not in config["venue"].get("tiers", {}):
                if "tiers" not in config["venue"]:
                    config["venue"]["tiers"] = {}
                config["venue"]["tiers"][level] = {
                    "elevation": elevation_map.get(elevation, 10.0),
                    "distance_range": list(distance_map.get(elevation, (30, 60))),
                }

    # Save updated config
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    return len(new_sections)


def get_available_venues() -> list[str]:
    """Get list of available venue IDs."""
    if not VENUES_DIR.exists():
        return []

    venues = []
    for venue_dir in VENUES_DIR.iterdir():
        if venue_dir.is_dir() and (venue_dir / "config.yaml").exists():
            venues.append(venue_dir.name)
    return venues


def load_seatmap_image(venue_id: str) -> Image.Image:
    """Load the seatmap image for a venue."""
    # Try to load from venue config
    config_path = VENUES_DIR / venue_id / "config.yaml"
    seatmap_path = VENUES_DIR / venue_id / "seatmap.png"

    if seatmap_path.exists():
        return Image.open(seatmap_path)

    # Return a placeholder if no image found
    return None


def main():
    st.set_page_config(
        page_title="Seat View Generator",
        page_icon="🏟️",
        layout="wide",
    )

    st.title("Seat View Generator")
    st.markdown("Click on a seat in the seatmap to see the view from that position.")

    # Sidebar for venue selection
    with st.sidebar:
        st.header("Settings")

        venues = get_available_venues()

        if not venues:
            st.warning("No venues configured yet.")
            st.markdown("""
            ### Quick Start

            To add a venue:
            1. Create a folder in `data/venues/<venue_id>/`
            2. Add `config.yaml` with venue configuration
            3. Add `seatmap.png` with the seatmap image

            See the example configuration below.
            """)

            # Show example config
            with st.expander("Example config.yaml"):
                st.code('''
venue:
  id: "yankee_stadium"
  name: "Yankee Stadium"
  type: "baseball"
  template: "baseball_stadium.blend"

  seatmap:
    file: "seatmap.png"
    width: 800
    height: 600

  field_center:
    x: 0
    y: 0
    z: 0

  tiers:
    100:
      elevation: 5.0
      distance_range: [30, 60]
    200:
      elevation: 15.0
      distance_range: [50, 80]
    400:
      elevation: 30.0
      distance_range: [70, 100]

  sections:
    - id: "101"
      tier: 100
      polygon: [[0.45, 0.65], [0.55, 0.65], [0.55, 0.75], [0.45, 0.75]]
      angle: 0
                ''', language='yaml')
            return

        venue_id = st.selectbox(
            "Select Venue",
            options=venues,
            format_func=lambda x: x.replace("_", " ").title()
        )

        st.divider()

        # Render quality settings
        st.subheader("Render Quality")
        quality = st.radio(
            "Quality",
            options=["preview", "full"],
            format_func=lambda x: "Preview (fast)" if x == "preview" else "Full Quality",
            help="Preview renders faster but at lower resolution"
        )

        st.divider()

        # AI Section Detection
        st.subheader("AI Section Detection")
        if OPENAI_API_KEY:
            st.caption("Use OpenAI Vision to auto-detect sections from the seatmap")
            if st.button("Analyze Seatmap with AI", type="secondary"):
                with st.spinner("Analyzing seatmap with OpenAI Vision..."):
                    try:
                        analysis = analyze_seatmap_with_ai(venue_id)
                        st.session_state["ai_analysis"] = analysis

                        # Show results
                        st.success(f"Detected {len(analysis.get('sections', []))} sections")
                        st.json({
                            "venue_type": analysis.get("venue_type"),
                            "sections_found": len(analysis.get("sections", [])),
                            "tiers_found": len(analysis.get("tiers", [])),
                        })

                        # Option to save
                        if st.button("Save to Config", key="save_ai"):
                            count = update_venue_config_with_ai_sections(venue_id, analysis)
                            st.success(f"Saved {count} sections to config!")
                            st.rerun()

                    except Exception as e:
                        st.error(f"Analysis failed: {str(e)}")

            # Show save button if we have pending analysis
            if "ai_analysis" in st.session_state:
                if st.button("Save AI Sections to Config"):
                    count = update_venue_config_with_ai_sections(
                        venue_id, st.session_state["ai_analysis"]
                    )
                    st.success(f"Saved {count} sections!")
                    del st.session_state["ai_analysis"]
                    st.rerun()
        else:
            st.warning("Set OPENAI_API_KEY to enable AI detection")

    # Main content area
    if venues:
        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("Seatmap")

            # Load seatmap image
            seatmap_image = load_seatmap_image(venue_id)

            if seatmap_image is None:
                st.error(f"Seatmap image not found for {venue_id}")
                st.info("Add a seatmap.png file to the venue folder.")
                return

            # Display clickable seatmap
            # Using streamlit-image-coordinates for click detection
            try:
                from streamlit_image_coordinates import streamlit_image_coordinates

                # Resize image to fit in container while maintaining aspect ratio
                max_width = 600
                orig_width, orig_height = seatmap_image.size
                if orig_width > max_width:
                    scale = max_width / orig_width
                    new_height = int(orig_height * scale)
                    display_image = seatmap_image.resize((max_width, new_height), Image.Resampling.LANCZOS)
                else:
                    display_image = seatmap_image
                    scale = 1.0

                # Display image and get click coordinates
                coords = streamlit_image_coordinates(
                    display_image,
                    key=f"seatmap_{venue_id}",
                )

                if coords is not None:
                    # Scale coordinates back to original image size
                    scaled_coords = {
                        "x": int(coords["x"] / scale) if scale != 1.0 else coords["x"],
                        "y": int(coords["y"] / scale) if scale != 1.0 else coords["y"],
                    }
                    st.session_state["last_click"] = scaled_coords
                    st.session_state["venue_id"] = venue_id

            except ImportError:
                # Fallback if streamlit-image-coordinates not installed
                st.image(seatmap_image, use_container_width=True)
                st.warning("Install streamlit-image-coordinates for click detection:")
                st.code("pip install streamlit-image-coordinates")

                # Manual coordinate input as fallback
                st.subheader("Manual Position Input")
                col_x, col_y = st.columns(2)
                with col_x:
                    click_x = st.number_input("X coordinate", min_value=0, value=400)
                with col_y:
                    click_y = st.number_input("Y coordinate", min_value=0, value=300)

                if st.button("Generate View"):
                    st.session_state["last_click"] = {"x": click_x, "y": click_y}
                    st.session_state["venue_id"] = venue_id

        with col2:
            st.subheader("View from Seat")

            # Check if we have a click to process
            if "last_click" in st.session_state and st.session_state.get("venue_id") == venue_id:
                coords = st.session_state["last_click"]
                click_x = coords["x"]
                click_y = coords["y"]

                st.info(f"Selected position: ({click_x}, {click_y})")

                try:
                    # Load venue and map coordinates
                    mapper = CoordinateMapper.load_venue(venue_id)

                    # Get section info (may be None for undefined areas)
                    section_info = mapper.get_section_info(click_x, click_y)

                    if section_info:
                        st.success(f"Section: {section_info['section_id']} (Tier {section_info['tier']})")
                    else:
                        st.info("Position estimated (not in defined section)")

                    # Always map to camera position - has fallback for undefined sections
                    camera = mapper.map_to_camera_position(click_x, click_y)

                    if camera:
                        # Show camera details in expander
                        with st.expander("Camera Position Details"):
                            st.json({
                                "position": {"x": round(camera.x, 2), "y": round(camera.y, 2), "z": round(camera.z, 2)},
                                "rotation": {
                                    "x": round(camera.rotation.x, 3),
                                    "y": round(camera.rotation.y, 3),
                                    "z": round(camera.rotation.z, 3)
                                },
                                "fov": camera.fov
                            })

                        # Render the view
                        if st.button("Render View", type="primary"):
                            with st.spinner("Rendering view... This may take 10-30 seconds."):
                                try:
                                    client = RenderClient(mapper.venue)

                                    if quality == "preview":
                                        image_data = client.render_preview(camera)
                                    else:
                                        image_data = client.render_full(camera)

                                    # Display the rendered image
                                    rendered_image = Image.open(io.BytesIO(image_data))
                                    st.image(rendered_image, caption="View from your seat", use_container_width=True)

                                    # Download button
                                    section_label = section_info['section_id'] if section_info else "estimated"
                                    st.download_button(
                                        label="Download Image",
                                        data=image_data,
                                        file_name=f"seat_view_{venue_id}_{section_label}.png",
                                        mime="image/png"
                                    )
                                except Exception as e:
                                    st.error(f"Render failed: {str(e)}")
                                    st.info("Make sure Modal is deployed: `modal deploy modal_backend/render_service.py`")

                except FileNotFoundError as e:
                    st.error(f"Venue configuration error: {e}")
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.info("Click on the seatmap to select a seat position.")

                # Show placeholder
                placeholder_text = """
                ### How it works

                1. **Click** on any seat in the seatmap
                2. The system identifies the **section and tier**
                3. It calculates the **3D camera position**
                4. **Blender renders** the view from that seat
                5. You see what the **actual view** looks like!

                The rendering uses a 3D model of the venue to create
                an accurate representation of the view.
                """
                st.markdown(placeholder_text)


if __name__ == "__main__":
    main()
