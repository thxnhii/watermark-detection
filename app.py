import streamlit as st
import asyncio
from figma_pipeline import FigmaPipeline
import os
import sys
from io import StringIO
import contextlib
import json
from PIL import Image
import nest_asyncio
from utils import clear_all_data, setup_directories
import plotly.express as px
import pandas as pd
from io import BytesIO

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

# Initialize session state
if 'initialized' not in st.session_state:
    clear_all_data()
    setup_directories()
    st.session_state.initialized = True

# Initialize all session state variables for storing results
if 'pipeline_results' not in st.session_state:
    st.session_state.pipeline_results = None
if 'figma_file_key_for_download' not in st.session_state:
    st.session_state.figma_file_key_for_download = None
if 'node_mappings' not in st.session_state:
    st.session_state.node_mappings = {}
if 'total_images' not in st.session_state:
    st.session_state.total_images = 0
if 'watermarked_images' not in st.session_state:
    st.session_state.watermarked_images = 0
if 'clean_images' not in st.session_state:
    st.session_state.clean_images = 0

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

    # Add clear results button
    if st.button("Clear Results", type="secondary"):
        clear_all_data()
        setup_directories()
        st.session_state.initialized = True
        st.session_state.pipeline_results = None
        st.session_state.figma_file_key_for_download = None
        st.session_state.node_mappings = {}
        st.session_state.total_images = 0
        st.session_state.watermarked_images = 0
        st.session_state.clean_images = 0
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
    """Run the pipeline and save all results to session state"""
    try:
        if not figma_file_key or not figma_access_token:
            st.error("Please provide both Figma File Key and Access Token")
            return

        # Clear all data and UI elements
        clear_all_data()
        setup_directories()
        st.session_state.initialized = True

        # Create containers for dynamic content
        status_container = st.empty()

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

            # Load results and save to session state
            if not os.path.exists("result.json"):
                st.error("No results found!")
                return

            with open("result.json", "r") as f:
                results = json.load(f)

            # Load node mappings
            node_mappings = {}
            if os.path.exists("node_mappings.json"):
                with open("node_mappings.json", "r") as f:
                    node_mappings = json.load(f)

            # Calculate metrics
            total_images = len(results)
            watermarked_images = sum(1 for r in results if r["status"])
            clean_images = total_images - watermarked_images

            # Sort results to prioritize watermark detected images
            results.sort(key=lambda x: not x["status"])

            # Save everything to session state
            st.session_state.pipeline_results = results
            st.session_state.figma_file_key_for_download = figma_file_key
            st.session_state.node_mappings = node_mappings
            st.session_state.total_images = total_images
            st.session_state.watermarked_images = watermarked_images
            st.session_state.clean_images = clean_images

            # Force rerun to display results
            st.rerun()

        finally:
            loop.close()

    except Exception as e:
        status_container.error(f"Error: {str(e)}")
        if debug_mode:
            st.exception(e)

def display_results():
    """Display results from session state"""
    
    # Create download button
    st.markdown("---")
    st.header("Download Results")
    excel_data = create_excel_download()
    if excel_data:
        st.download_button(
            label="Download Results as Excel",
            data=excel_data,
            file_name="figma_watermark_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # Display overall results
    st.header("Overall Results")

    # Display metrics in columns
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Images Processed", st.session_state.total_images)
    with col2:
        st.metric("Images with Watermark", st.session_state.watermarked_images)
    with col3:
        st.metric("Images without Watermark", st.session_state.clean_images)

    # Display pie chart using Plotly
    if st.session_state.total_images > 0:
        fig = px.pie(
            names=["With Watermark", "Without Watermark"],
            values=[st.session_state.watermarked_images, st.session_state.clean_images],
            title="Watermark Detection Distribution",
            color_discrete_sequence=["#FF6384", "#36A2EB"]
        )
        st.plotly_chart(fig, use_container_width=True)

    # Display detailed results
    st.header("Detailed Results")

    # Table-like display
    results = st.session_state.pipeline_results
    node_mappings = st.session_state.node_mappings
    figma_file_key = st.session_state.figma_file_key_for_download

    if results:
        for result in results:
            image_ref = os.path.splitext(os.path.basename(result["image"]))[0]
            node_urls = []
            if image_ref in node_mappings:
                for node in node_mappings[image_ref]:
                    url = f"https://www.figma.com/file/{figma_file_key}?node-id={node['node_id']}"
                    node_urls.append(f"<li><a href='{url}' target='_blank'>{node['name']}</a></li>")

            # Create unordered list for node links
            node_links_html = "<ul class='node-links'>" + "".join(node_urls) + "</ul>" if node_urls else "N/A"

            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                try:
                    image = Image.open(result["image"])
                    st.image(image, width=100)
                except Exception as e:
                    st.error(f"Error loading image: {str(e)}")
            with col2:
                status_text = "🔴 Watermark Detected" if result["status"] else "🟢 No Watermark"
                st.write(status_text)
            with col3:
                st.markdown(node_links_html, unsafe_allow_html=True)
            st.markdown("---")
    else:
        st.info("No results to display.")

    # Image grid display
    st.header("Processed Images")
    if results:
        cols = st.columns(3)
        for idx, result in enumerate(results):
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

def create_excel_download():
    """Create Excel download from session state"""
    if not st.session_state.pipeline_results:
        st.error("No results available for download. Please run the pipeline first.")
        return None
    
    results = st.session_state.pipeline_results
    figma_file_key = st.session_state.figma_file_key_for_download
    node_mappings = st.session_state.node_mappings
    total_images = st.session_state.total_images
    watermarked_images = st.session_state.watermarked_images
    clean_images = st.session_state.clean_images
    
    # Prepare overall results DataFrame
    overall_data = {
        "Metric": ["Total Images Processed", "Images with Watermark", "Images without Watermark"],
        "Value": [total_images, watermarked_images, clean_images]
    }
    df_overall = pd.DataFrame(overall_data)
    
    # Prepare detailed results DataFrame
    excel_csv_data = []
    for result in results:
        image_ref = os.path.splitext(os.path.basename(result["image"]))[0]
        node_links = []
        if image_ref in node_mappings:
            for node in node_mappings[image_ref]:
                url = f"https://www.figma.com/file/{figma_file_key}?node-id={node['node_id']}"
                node_links.append(f"• {url}")
            node_links_str = "\n".join(node_links)
        else:
            node_links_str = "N/A"
        excel_csv_data.append({
            "Image": result["image"],
            "Status": "🔴 Watermark Detected" if result["status"] else "🟢 No Watermark",
            "Node Links": node_links_str
        })
    df_detailed = pd.DataFrame(excel_csv_data)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_overall.to_excel(writer, index=False, sheet_name='Overall Result')
        df_detailed.to_excel(writer, index=False, sheet_name='Detailed Results')
        
        # Set column widths and wrap text for Node Links column
        workbook  = writer.book
        worksheet_detailed = writer.sheets['Detailed Results']
        # Set minimum width (e.g., 60) and wrap text for Node Links (column C, index 2)
        wrap_format = workbook.add_format({'text_wrap': True})
        worksheet_detailed.set_column('C:C', 80, wrap_format)
    output.seek(0)
    
    return output

# Run button
if st.button("Run Pipeline", type="primary"):
    run_pipeline()

# Check if results exist in session state and display them
if st.session_state.pipeline_results:
    display_results()
else:
    st.markdown("---")
    st.info("Run the pipeline first to see results and enable download functionality.")