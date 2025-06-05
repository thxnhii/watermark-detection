import streamlit as st
import asyncio
from figma_pipeline import FigmaPipeline
import os
import sys
from io import StringIO
import contextlib
import json
from PIL import Image
import shutil
import nest_asyncio
from utils import clear_all_data, setup_directories

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

# Initialize session state
if 'initialized' not in st.session_state:
    clear_all_data()
    st.session_state.initialized = True

st.set_page_config(
    page_title="Figma Watermark Detection",
    page_icon="🎨",
    layout="wide"
)

st.title("🎨 Figma Watermark Detection")

# Sidebar for configuration
with st.sidebar:
    st.header("Configuration")
    figma_file_key = st.text_input("Figma File Key", help="The key from your Figma file URL")
    figma_access_token = st.text_input("Figma Access Token", type="password", help="Your Figma access token")
    batch_size = st.number_input("Batch Size", min_value=1, max_value=50, value=10, help="Number of images to process in each batch")
    debug_mode = st.checkbox("Debug Mode", help="Show detailed debug information")
    
    # Add clear results button
    if st.button("Clear Results", type="secondary"):
        clear_all_data()
        st.session_state.initialized = True
        st.success("All data cleared!")
        st.rerun()

# Main content
st.markdown("""
This application helps you detect watermarks in images from your Figma files. 
Follow these steps to get started:

1. Enter your Figma File Key and Access Token in the sidebar
2. Adjust the batch size if needed
3. Click the 'Run Pipeline' button to start processing
""")

# Status display
status_placeholder = st.empty()
progress_placeholder = st.empty()
debug_placeholder = st.empty()

# Progress bars container
progress_container = st.container()

# Initialize progress bars in session state
if 'progress_bars' not in st.session_state:
    st.session_state.progress_bars = {
        'Overall Progress': 0.0,
        'Fetching Figma images': 0.0,
        'Downloading batch': 0.0,
        'Detecting watermarks': 0.0
    }

def update_progress(stage: str, progress: float):
    """Update progress for a specific stage"""
    st.session_state.progress_bars[stage] = progress
    
    # Update the progress bars display
    with progress_container:
        for stage_name, stage_progress in st.session_state.progress_bars.items():
            if stage_name == 'Downloading batch':
                # Show the current batch progress
                st.progress(stage_progress, text=f"{stage_name}: {stage_progress:.0%}")
            else:
                st.progress(stage_progress, text=f"{stage_name}: {stage_progress:.0%}")

# Show total processed images and results
if os.path.exists("result.json"):
    with open("result.json", "r") as f:
        results = json.load(f)
        st.sidebar.metric("Total Processed Images", len(results))
        
        # Display images in a grid
        st.header("Processed Images")
        
        # Create columns for the grid
        cols = st.columns(3)  # 3 images per row
        
        for idx, result in enumerate(results):
            col_idx = idx % 3
            with cols[col_idx]:
                try:
                    # Get the output image path
                    output_path = result["image"]
                    if os.path.exists(output_path):
                        # Display image
                        image = Image.open(output_path)
                        st.image(image, use_container_width=True)
                        
                        # Display status with color
                        if result["status"]:
                            st.error("Watermark Detected")
                        else:
                            st.success("No Watermark")
                            
                        # Display filename
                        st.caption(os.path.basename(output_path))
                    else:
                        st.error(f"Image not found: {output_path}")
                except Exception as e:
                    st.error(f"Error loading image: {str(e)}")

@contextlib.contextmanager
def capture_output():
    new_out, new_err = StringIO(), StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = new_out, new_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = old_out, old_err

def run_pipeline():
    """Run the pipeline in a synchronous way"""
    try:
        if not figma_file_key or not figma_access_token:
            st.error("Please provide both Figma File Key and Access Token")
            return

        # Clear previous results before starting new pipeline
        clear_all_data()
        
        # Reset progress bars
        st.session_state.progress_bars = {
            'Overall Progress': 0.0,
            'Fetching Figma images': 0.0,
            'Downloading batch': 0.0,
            'Detecting watermarks': 0.0
        }
        
        status_placeholder.info("Initializing pipeline...")
        
        pipeline = FigmaPipeline(
            figma_file_key=figma_file_key,
            figma_access_token=figma_access_token,
            batch_size=batch_size,
            progress_callback=update_progress
        )
        
        status_placeholder.info("Starting pipeline...")
        
        # Create a single event loop for the entire pipeline
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Run the pipeline using the FigmaPipeline's run_pipeline method
            loop.run_until_complete(pipeline.run_pipeline())
            status_placeholder.success("Pipeline completed successfully!")
            st.rerun()  # Refresh the page to show new results
        finally:
            # Clean up the event loop
            loop.close()
                
    except Exception as e:
        status_placeholder.error(f"Error: {str(e)}")
        if debug_mode:
            debug_placeholder.exception(e)

# Run button
if st.button("Run Pipeline", type="primary"):
    run_pipeline() 