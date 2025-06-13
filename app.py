import streamlit as st
import asyncio
from figma_pipeline import FigmaPipeline
import os
import json
import sys
from io import StringIO
import contextlib
import json
from PIL import Image
import nest_asyncio
from utils import clear_all_data, setup_directories
import plotly.express as px
import math

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

# Initialize session state
if 'initialized' not in st.session_state:
    clear_all_data()
    setup_directories()
    st.session_state.initialized = True
if 'results_page' not in st.session_state:
    st.session_state.results_page = 1
if 'images_page' not in st.session_state:
    st.session_state.images_page = 1

st.set_page_config(
    page_title="Figma Watermark Detection",
    page_icon="🎨",
    layout="wide"
)

# Custom CSS for link and list styling
st.markdown("""
<style>
a { 
    color: #1a0dab; 
    text-decoration: none; 
}
a:hover { 
    text-decoration: underline; 
}
ul.node-links { 
    margin: 0; 
    padding-left: 20px; 
    list-style-type: disc; 
}
ul.node-links li { 
    margin-bottom: 5px; 
}
</style>
""", unsafe_allow_html=True)

st.title("🎨 Figma Watermark Detection")

# Sidebar for configuration
with st.sidebar:
    st.header("Configuration")
    figma_access_token = st.text_input("Figma Access Token", type="password", help="Your Figma access token")
    figma_file_key = st.text_input("Figma File Key", help="The key from your Figma file URL")
    batch_size = st.number_input("Batch Size", min_value=1, max_value=50, value=10, help="Number of images to process in each batch")
    debug_mode = st.checkbox("Debug Mode", help="Show detailed debug information")
    
    # Pagination settings
    items_per_page = st.selectbox("Items per page", [5, 10, 20, 50], index=1, help="Number of items to display per page")

    # Add clear results button
    if st.button("Clear Results", type="secondary"):
        clear_all_data()
        setup_directories()
        st.session_state.initialized = True
        st.session_state.results_page = 1
        st.session_state.images_page = 1
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

def display_pagination(total_items, items_per_page, page_key, label):
    """Display pagination controls"""
    total_pages = math.ceil(total_items / items_per_page)
    current_page = st.session_state[page_key]
    
    st.subheader(f"{label} (Page {current_page} of {total_pages})")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("Previous", disabled=(current_page <= 1), key=f"prev_{page_key}"):
            st.session_state[page_key] -= 1
            st.rerun()
    with col2:
        page_options = list(range(1, total_pages + 1))
        new_page = st.selectbox("Go to page", page_options, index=current_page-1, key=f"select_{page_key}", label_visibility="collapsed")
        if new_page != current_page:
            st.session_state[page_key] = new_page
            st.rerun()
    with col3:
        if st.button("Next", disabled=(current_page >= total_pages), key=f"next_{page_key}"):
            st.session_state[page_key] += 1
            st.rerun()
    
    return current_page

def run_pipeline():
    """Run the pipeline and display overall and detailed results"""
    try:
        if not figma_file_key or not figma_access_token:
            st.error("Please provide both Figma File Key and Access Token")
            return

        # Clear all data and UI elements
        clear_all_data()
        setup_directories()
        st.session_state.initialized = True
        st.session_state.results_page = 1
        st.session_state.images_page = 1
        
        # Create containers for dynamic content
        status_container = st.empty()
        overall_container = st.empty()
        results_container = st.empty()
        table_container = st.empty()
        images_container = st.empty()
        
        status_container.info("Initializing pipeline...")

        pipeline = FigmaPipeline(
            figma_file_key=figma_file_key,
            figma_access_token=figma_access_token,
            batch_size=batch_size,
            debug_mode=debug_mode
        )

        status_container.info("Starting pipeline...")

        # Create and run event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Run the pipeline
            loop.run_until_complete(pipeline.run_pipeline())
            status_container.success("Pipeline completed successfully!")
            
            # Load results
            if not os.path.exists("result.json"):
                st.error("No results found!")
                return

            with open("result.json", "r") as f:
                results = json.load(f)

            # Sort results to prioritize watermark detected images
            results.sort(key=lambda x: not x["status"])  # True (watermark) comes before False (no watermark)

            # --- Overall Results Section ---
            with overall_container.container():
                st.header("Overall Results")
                
                # Calculate metrics
                total_images = len(results)
                watermarked_images = sum(1 for r in results if r["status"])
                clean_images = total_images - watermarked_images
                
                # Display metrics in columns
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Images Processed", total_images)
                with col2:
                    st.metric("Images with Watermark", watermarked_images)
                with col3:
                    st.metric("Images without Watermark", clean_images)

                # Display pie chart using Plotly
                if total_images > 0:
                    fig = px.pie(
                        names=["With Watermark", "Without Watermark"],
                        values=[watermarked_images, clean_images],
                        title="Watermark Detection Distribution",
                        color_discrete_sequence=["#FF6384", "#36A2EB"]
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    if debug_mode:
                        st.info("Plotly pie chart rendered. Check browser console (F12) for any errors.")

            # --- Detailed Results Section ---
            with results_container.container():
                st.header("Detailed Results")
                
                # Load node mappings
                node_mappings = {}
                if os.path.exists("node_mappings.json"):
                    with open("node_mappings.json", "r") as f:
                        node_mappings = json.load(f)
                
                # Pagination for detailed results
                current_page = display_pagination(len(results), items_per_page, 'results_page', 'Detailed Results')
                start_idx = (current_page - 1) * items_per_page
                end_idx = start_idx + items_per_page
                paginated_results = results[start_idx:end_idx]
                
                # Table-like display
                with table_container.container():
                    table_data = []
                    for result in paginated_results:
                        image_ref = os.path.splitext(os.path.basename(result["image"]))[0]
                        node_urls = []
                        if image_ref in node_mappings:
                            for node in node_mappings[image_ref]:
                                url = f"https://www.figma.com/board/{figma_file_key}?node-id={node['node_id']}"
                                node_urls.append(f"<li><a href='{url}' target='_blank'>{node['name']}</a></li>")
                        
                        # Create unordered list for node links
                        node_links_html = "<ul class='node-links'>" + "".join(node_urls) + "</ul>" if node_urls else "N/A"
                        
                        table_data.append({
                            "Image": result["image"],
                            "Status": "🔴 Watermark Detected" if result["status"] else "🟢 No Watermark",
                            "Node Links": node_links_html
                        })
                    
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
                                st.markdown(row["Node Links"], unsafe_allow_html=True)
                            st.markdown("---")
                    else:
                        st.info("No results to display.")
                
                # Image grid display
                with images_container.container():
                    st.header("Processed Images")
                    
                    # Pagination for processed images
                    current_page = display_pagination(len(results), items_per_page, 'images_page', 'Processed Images')
                    start_idx = (current_page - 1) * items_per_page
                    end_idx = start_idx + items_per_page
                    paginated_results = results[start_idx:end_idx]
                    
                    cols = st.columns(3)
                    for idx, result in enumerate(paginated_results):
                        col_idx = idx % 3
                        with cols[col_idx]:
                            try:
                                output_path = result["image"]
                                if os.path.exists(output_path):
                                    image = Image.open(output_path)
                                    st.image(image)
                                    if result["status"]:
                                        st.error("Watermark Detected")
                                    else:
                                        st.success("No Watermark")
                                    st.caption(os.path.basename(output_path))
                                else:
                                    st.error(f"Image not found: {output_path}")
                            except Exception as e:
                                st.error(f"Error loading image: {str(e)}")
        
        finally:
            loop.close()

    except Exception as e:
        status_container.error(f"Error: {str(e)}")
        if debug_mode:
            st.exception(e)

# Run button
if st.button("Run Pipeline", type="primary"):
    run_pipeline()