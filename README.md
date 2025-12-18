# Seat View Generator

Generate accurate 3D views from any seat in a stadium or arena by clicking on a seatmap.

## Overview

This system creates realistic seat view images for ticket platforms:

1. **Click** on a seatmap to select a seat position
2. **Map** the 2D coordinates to a 3D camera position
3. **Render** the view using Blender on GPU (via Modal)
4. **Display** the rendered view to the user

## Quick Start

### 1. Install Dependencies

```bash
cd gametime-images
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Set Up Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Authenticate with Modal

```bash
modal token new
```

### 4. Deploy the Render Backend

```bash
modal deploy modal_backend/render_service.py
```

### 5. Test the Backend

```bash
python scripts/test_render.py
```

### 6. Run the App

```bash
streamlit run app/streamlit_app.py
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    STREAMLIT FRONTEND                            │
│  [Venue Select] → [Seatmap Display] → [Click Handler] → [View]  │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                  COORDINATE MAPPING SERVICE                      │
│  [Click (x,y)] → [Find Section] → [Calculate 3D Camera Pos]     │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MODAL BACKEND (GPU)                           │
│  [Load Template] → [Position Camera] → [Blender Render] → PNG   │
└─────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
gametime-images/
├── app/
│   ├── streamlit_app.py           # Main UI
│   ├── config.py                  # Configuration
│   ├── services/
│   │   ├── coordinate_mapper.py   # 2D → 3D mapping
│   │   ├── render_client.py       # Modal client
│   │   └── render_cache.py        # Caching layer
│   ├── models/
│   │   ├── venue.py               # Venue data models
│   │   └── camera.py              # Camera models
│   └── utils/
│       └── geometry.py            # Polygon math
├── modal_backend/
│   └── render_service.py          # Blender GPU rendering
├── data/
│   ├── venues/                    # Venue configurations
│   │   ├── yankee_stadium/
│   │   │   ├── config.yaml
│   │   │   └── seatmap.png
│   │   └── lenovo_center/
│   └── templates/                 # Blender .blend files
├── scripts/
│   ├── deploy_modal.py
│   ├── test_render.py
│   └── test_mapping.py
└── requirements.txt
```

## Adding a New Venue

1. Create a folder: `data/venues/<venue_id>/`

2. Add the seatmap image: `seatmap.png`

3. Create `config.yaml`:

```yaml
venue:
  id: "my_venue"
  name: "My Venue"
  type: "hockey"  # baseball, hockey, basketball, football
  template: "hockey_arena.blend"

  seatmap:
    file: "seatmap.png"
    width: 1280
    height: 968

  field_center:
    x: 0
    y: 0
    z: 0

  tiers:
    100:
      elevation: 5.0
      distance_range: [20, 40]
    200:
      elevation: 15.0
      distance_range: [35, 55]

  sections:
    - id: "101"
      tier: 100
      polygon: [[0.2, 0.4], [0.3, 0.4], [0.3, 0.5], [0.2, 0.5]]
      angle: 0
```

4. Define section polygons (normalized 0-1 coordinates)

5. Test with: `python scripts/test_mapping.py my_venue`

## Blender Templates

Templates are stored in the Modal volume. To add a template:

1. Download a 3D stadium model from [TurboSquid](https://www.turbosquid.com/3d-model/free/stadium) or [Free3D](https://free3d.com/3d-models/stadium)

2. Import into Blender and standardize:
   - Origin at field/ice center
   - Scale in meters
   - Z-up orientation

3. Upload to Modal volume (use the `upload_template` function)

## Cost Estimates

| Service | Usage | Cost |
|---------|-------|------|
| Modal GPU (L40S) | Per render | ~$0.01-0.02 |
| OpenAI GPT-4V | Venue setup | ~$0.02/venue |
| Replicate Flux | Venue setup | ~$0.05/venue |

With caching, expect ~$75-100/month at 10,000 renders.

## Development

### Test Coordinate Mapping

```bash
python scripts/test_mapping.py yankee_stadium
```

### Test Modal Backend

```bash
python scripts/test_render.py
```

### Run Streamlit Locally

```bash
streamlit run app/streamlit_app.py
```
