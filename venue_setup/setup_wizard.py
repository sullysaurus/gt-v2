"""Streamlit wizard for setting up new venues."""
import streamlit as st
from PIL import Image, ImageDraw
from pathlib import Path
import yaml
import json
import sys
import io

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import VENUES_DIR, DATA_DIR
from app.services.openai_analyzer import SeatmapAnalyzer
from app.services.depth_estimator import DepthEstimator


def draw_sections_on_image(image: Image.Image, sections: list) -> Image.Image:
    """Draw section polygons on the seatmap image."""
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy, "RGBA")

    width, height = image.size

    colors = [
        (255, 0, 0, 100),    # Red
        (0, 255, 0, 100),    # Green
        (0, 0, 255, 100),    # Blue
        (255, 255, 0, 100),  # Yellow
        (255, 0, 255, 100),  # Magenta
        (0, 255, 255, 100),  # Cyan
    ]

    for i, section in enumerate(sections):
        polygon = section.get("polygon", [])
        if len(polygon) >= 3:
            # Convert normalized coords to pixel coords
            pixel_polygon = [
                (int(p[0] * width), int(p[1] * height))
                for p in polygon
            ]
            color = colors[i % len(colors)]
            draw.polygon(pixel_polygon, fill=color, outline=(255, 255, 255, 200))

            # Draw section ID
            if pixel_polygon:
                center_x = sum(p[0] for p in pixel_polygon) // len(pixel_polygon)
                center_y = sum(p[1] for p in pixel_polygon) // len(pixel_polygon)
                draw.text(
                    (center_x, center_y),
                    section.get("id", "?"),
                    fill=(255, 255, 255, 255)
                )

    return img_copy


def main():
    st.set_page_config(
        page_title="Venue Setup Wizard",
        page_icon="🏗️",
        layout="wide",
    )

    st.title("🏗️ Venue Setup Wizard")
    st.markdown("Configure a new venue for seat view generation.")

    # Initialize session state
    if "setup_step" not in st.session_state:
        st.session_state.setup_step = 1
    if "analysis_result" not in st.session_state:
        st.session_state.analysis_result = None
    if "venue_config" not in st.session_state:
        st.session_state.venue_config = None

    # Sidebar for navigation
    with st.sidebar:
        st.header("Setup Progress")
        steps = [
            "1. Upload Seatmap",
            "2. AI Analysis",
            "3. Review & Edit",
            "4. Save Configuration",
        ]
        for i, step in enumerate(steps, 1):
            if i < st.session_state.setup_step:
                st.success(step)
            elif i == st.session_state.setup_step:
                st.info(f"→ {step}")
            else:
                st.text(step)

    # Step 1: Upload seatmap
    if st.session_state.setup_step == 1:
        st.header("Step 1: Upload Seatmap Image")

        col1, col2 = st.columns([2, 1])

        with col1:
            uploaded_file = st.file_uploader(
                "Upload your seatmap image",
                type=["png", "jpg", "jpeg"],
                help="Upload a top-down view of the venue seatmap"
            )

            if uploaded_file:
                image = Image.open(uploaded_file)
                st.image(image, caption=f"Seatmap ({image.size[0]}x{image.size[1]})")
                st.session_state.uploaded_image = image
                st.session_state.image_bytes = uploaded_file.getvalue()

        with col2:
            st.subheader("Venue Details")

            venue_id = st.text_input(
                "Venue ID",
                placeholder="yankee_stadium",
                help="Unique identifier (lowercase, underscores)"
            )
            venue_name = st.text_input(
                "Venue Name",
                placeholder="Yankee Stadium",
                help="Display name for the venue"
            )
            venue_type = st.selectbox(
                "Venue Type",
                options=["baseball", "hockey", "basketball", "football", "concert", "other"]
            )

            st.session_state.venue_id = venue_id
            st.session_state.venue_name = venue_name
            st.session_state.venue_type = venue_type

        if uploaded_file and venue_id and venue_name:
            if st.button("Continue to Analysis", type="primary"):
                st.session_state.setup_step = 2
                st.rerun()

    # Step 2: AI Analysis
    elif st.session_state.setup_step == 2:
        st.header("Step 2: AI Analysis")

        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("Original Seatmap")
            if "uploaded_image" in st.session_state:
                st.image(st.session_state.uploaded_image)

        with col2:
            st.subheader("Analysis Options")

            use_openai = st.checkbox("Use OpenAI Vision for section detection", value=True)
            use_depth = st.checkbox("Generate depth map for elevation hints", value=False)

            if st.button("Run Analysis", type="primary"):
                with st.spinner("Analyzing seatmap..."):
                    try:
                        # Save image temporarily
                        temp_path = Path("/tmp/temp_seatmap.png")
                        st.session_state.uploaded_image.save(temp_path)

                        results = {}

                        if use_openai:
                            st.info("Running OpenAI Vision analysis...")
                            analyzer = SeatmapAnalyzer()
                            analysis = analyzer.analyze(temp_path)
                            results["openai_analysis"] = analysis
                            st.success(f"Found {len(analysis.get('sections', []))} sections")

                        if use_depth:
                            st.info("Generating depth map...")
                            try:
                                estimator = DepthEstimator()
                                depth_image = estimator.estimate_depth_marigold(temp_path)
                                results["depth_image"] = depth_image
                                st.success("Depth map generated")
                            except Exception as e:
                                st.warning(f"Depth estimation failed: {e}")

                        st.session_state.analysis_result = results

                        # Generate initial config
                        if "openai_analysis" in results:
                            image = st.session_state.uploaded_image
                            analysis = results["openai_analysis"]

                            # Build config from analysis
                            tier_configs = {}
                            elevation_map = {"low": 5.0, "medium": 15.0, "high": 28.0, "very_high": 40.0}
                            distance_map = {"low": (25, 50), "medium": (45, 70), "high": (60, 85), "very_high": (75, 100)}

                            for tier in analysis.get("tiers", []):
                                level = tier.get("level", 100)
                                elevation = tier.get("relative_elevation", "low")
                                tier_configs[level] = {
                                    "elevation": elevation_map.get(elevation, 10.0),
                                    "distance_range": list(distance_map.get(elevation, (30, 60))),
                                }

                            sections = []
                            for section in analysis.get("sections", []):
                                sections.append({
                                    "id": str(section.get("id", "")),
                                    "tier": section.get("tier", 100),
                                    "polygon": section.get("approximate_polygon", []),
                                    "angle": section.get("angle_from_center", 0),
                                })

                            template_map = {
                                "baseball": "baseball_stadium.blend",
                                "hockey": "hockey_arena.blend",
                                "basketball": "basketball_arena.blend",
                                "football": "football_stadium.blend",
                            }

                            st.session_state.venue_config = {
                                "venue": {
                                    "id": st.session_state.venue_id,
                                    "name": st.session_state.venue_name,
                                    "type": st.session_state.venue_type,
                                    "template": template_map.get(st.session_state.venue_type, "generic.blend"),
                                    "seatmap": {
                                        "file": "seatmap.png",
                                        "width": image.size[0],
                                        "height": image.size[1],
                                    },
                                    "field_center": {"x": 0, "y": 0, "z": 0},
                                    "tiers": tier_configs if tier_configs else {
                                        100: {"elevation": 5.0, "distance_range": [30, 55]},
                                        200: {"elevation": 18.0, "distance_range": [50, 80]},
                                        300: {"elevation": 30.0, "distance_range": [65, 95]},
                                    },
                                    "sections": sections,
                                }
                            }

                        st.session_state.setup_step = 3
                        st.rerun()

                    except Exception as e:
                        st.error(f"Analysis failed: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        if st.button("← Back"):
            st.session_state.setup_step = 1
            st.rerun()

    # Step 3: Review & Edit
    elif st.session_state.setup_step == 3:
        st.header("Step 3: Review & Edit Configuration")

        if st.session_state.venue_config is None:
            st.error("No configuration generated. Please go back and run analysis.")
            if st.button("← Back"):
                st.session_state.setup_step = 2
                st.rerun()
            return

        config = st.session_state.venue_config["venue"]

        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("Section Visualization")

            # Draw sections on image
            if "uploaded_image" in st.session_state:
                sections = config.get("sections", [])
                annotated = draw_sections_on_image(
                    st.session_state.uploaded_image,
                    sections
                )
                st.image(annotated, caption=f"{len(sections)} sections detected")

            # Show depth map if available
            if st.session_state.analysis_result and "depth_image" in st.session_state.analysis_result:
                with st.expander("Depth Map"):
                    st.image(st.session_state.analysis_result["depth_image"])

        with col2:
            st.subheader("Edit Configuration")

            # Tier settings
            with st.expander("Tier Settings", expanded=True):
                tiers = config.get("tiers", {})
                updated_tiers = {}

                for tier_level, tier_config in tiers.items():
                    st.markdown(f"**Tier {tier_level}**")
                    col_a, col_b, col_c = st.columns(3)

                    with col_a:
                        elevation = st.number_input(
                            f"Elevation (m)",
                            value=float(tier_config.get("elevation", 10)),
                            key=f"tier_{tier_level}_elev"
                        )
                    with col_b:
                        min_dist = st.number_input(
                            f"Min Distance",
                            value=float(tier_config.get("distance_range", [30, 60])[0]),
                            key=f"tier_{tier_level}_min"
                        )
                    with col_c:
                        max_dist = st.number_input(
                            f"Max Distance",
                            value=float(tier_config.get("distance_range", [30, 60])[1]),
                            key=f"tier_{tier_level}_max"
                        )

                    updated_tiers[tier_level] = {
                        "elevation": elevation,
                        "distance_range": [min_dist, max_dist]
                    }

                config["tiers"] = updated_tiers

            # Section list
            with st.expander("Sections", expanded=False):
                sections = config.get("sections", [])
                st.markdown(f"**{len(sections)} sections defined**")

                # Allow editing section JSON directly
                sections_json = st.text_area(
                    "Sections JSON (advanced)",
                    value=json.dumps(sections, indent=2),
                    height=300
                )

                try:
                    updated_sections = json.loads(sections_json)
                    config["sections"] = updated_sections
                except json.JSONDecodeError:
                    st.error("Invalid JSON")

            # Raw config view
            with st.expander("Full Configuration (YAML)"):
                st.code(yaml.dump(st.session_state.venue_config, default_flow_style=False))

        col_back, col_next = st.columns(2)
        with col_back:
            if st.button("← Back to Analysis"):
                st.session_state.setup_step = 2
                st.rerun()
        with col_next:
            if st.button("Continue to Save →", type="primary"):
                st.session_state.setup_step = 4
                st.rerun()

    # Step 4: Save Configuration
    elif st.session_state.setup_step == 4:
        st.header("Step 4: Save Configuration")

        config = st.session_state.venue_config
        venue_id = config["venue"]["id"]

        st.subheader("Configuration Summary")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Venue", config["venue"]["name"])
            st.metric("Type", config["venue"]["type"])
            st.metric("Sections", len(config["venue"]["sections"]))

        with col2:
            st.metric("Tiers", len(config["venue"]["tiers"]))
            st.metric("Image Size", f"{config['venue']['seatmap']['width']}x{config['venue']['seatmap']['height']}")

        st.divider()

        # Save options
        venue_dir = VENUES_DIR / venue_id

        if venue_dir.exists():
            st.warning(f"Venue directory already exists: {venue_dir}")
            overwrite = st.checkbox("Overwrite existing configuration")
        else:
            overwrite = True

        if st.button("Save Configuration", type="primary", disabled=not overwrite):
            try:
                # Create directory
                venue_dir.mkdir(parents=True, exist_ok=True)

                # Save config
                config_path = venue_dir / "config.yaml"
                with open(config_path, "w") as f:
                    yaml.dump(config, f, default_flow_style=False)

                # Save seatmap image
                seatmap_path = venue_dir / "seatmap.png"
                st.session_state.uploaded_image.save(seatmap_path)

                st.success(f"Configuration saved to {venue_dir}")
                st.balloons()

                # Show next steps
                st.subheader("Next Steps")
                st.markdown(f"""
                1. **Test the configuration:**
                   ```bash
                   python scripts/test_mapping.py {venue_id}
                   ```

                2. **Run the main app:**
                   ```bash
                   streamlit run app/streamlit_app.py
                   ```

                3. **Refine sections** if needed by editing:
                   `{config_path}`
                """)

            except Exception as e:
                st.error(f"Failed to save: {e}")

        # Download options
        st.divider()
        st.subheader("Download Configuration")

        col1, col2 = st.columns(2)
        with col1:
            config_yaml = yaml.dump(config, default_flow_style=False)
            st.download_button(
                "Download config.yaml",
                data=config_yaml,
                file_name="config.yaml",
                mime="text/yaml"
            )

        with col2:
            if "image_bytes" in st.session_state:
                st.download_button(
                    "Download seatmap.png",
                    data=st.session_state.image_bytes,
                    file_name="seatmap.png",
                    mime="image/png"
                )

        if st.button("← Back to Edit"):
            st.session_state.setup_step = 3
            st.rerun()


if __name__ == "__main__":
    main()
