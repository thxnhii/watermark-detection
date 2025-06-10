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
    figma_access_token = st.text_input("Figma Access Token", type="password", help="Your Figma access token")
    figma_file_key = st.text_input("Figma File Key", help="The key from your Figma file URL")
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

1. Enter your Figma Access Token and File Key in the sidebar
2. Adjust the batch size if needed
3. Click the 'Run Pipeline' button to start processing
""")

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

        # Clear all data and UI elements, same as Clear Results button
        clear_all_data()
        st.session_state.initialized = True
        
        # Create containers for dynamic content
        status_container = st.empty()
        results_container = st.empty()
        
        status_container.info("Initializing pipeline...")

        pipeline = FigmaPipeline(
            figma_file_key=figma_file_key,
            figma_access_token=figma_access_token,
            batch_size=batch_size,
            debug_mode=debug_mode
        )

        status_container.info("Starting pipeline...")

        # Create a single event loop for the entire pipeline
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Run the pipeline
            loop.run_until_complete(pipeline.run_pipeline())
            status_container.success("Pipeline completed successfully!")
            
            # Display results
            if os.path.exists("result.json"):
                with open("result.json", "r") as f:
                    results = json.load(f)
                    st.sidebar.metric("Total Processed Images", len(results))
                    
                    # Create separate containers for table and images
                    table_container = st.container()
                    images_container = st.container()
                    
                    # Display table in its container
                    with table_container:
                        st.header("Detailed Results")
                        
                        # Load node mappings
                        if os.path.exists("node_mappings.json"):
                            with open("node_mappings.json", "r") as f:
                                node_mappings = json.load(f)
                            
                            # Create a table with the requested information
                            table_data = []
                            
                            for result in results:
                                image_ref = os.path.splitext(os.path.basename(result["image"]))[0]
                                if image_ref in node_mappings:
                                    # Create list of node URLs
                                    node_urls = []
                                    for node in node_mappings[image_ref]:
                                        url = f"https://www.figma.com/board/{figma_file_key}?node-id={node['node_id']}"
                                        node_urls.append(f"[{node['name']}]({url})")
                                    
                                    # Add row to table data
                                    table_data.append({
                                        "Image": result["image"],
                                        "Status": "🔴 Watermark Detected" if result["status"] else "🟢 No Watermark",
                                        "Node Links": "\n".join(node_urls)
                                    })
                            
                            # Display the table
                            if table_data:
                                for row in table_data:
                                    col1, col2, col3 = st.columns([1, 1, 2])
                                    with col1:
                                        try:
                                            image = Image.open(row["Image"])
                                            st.image(image, width=100)
                                        except Exception as e:
                                            st.error(f"Error loading image: {str(e)}")
                                    with col2:
                                        st.write(row["Status"])
                                    with col3:
                                        st.markdown(row["Node Links"])
                                    st.markdown("---")
                    
                    # Display images in their container
                    with images_container:
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
                                        st.image(image)
                                        
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
                        
        finally:
            # Clean up the event loop
            loop.close()

    except Exception as e:
        status_container.error(f"Error: {str(e)}")
        if debug_mode:
            st.exception(e)

# Run button
if st.button("Run Pipeline", type="primary"):
    run_pipeline()

