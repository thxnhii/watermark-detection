import os
import shutil
from typing import List, Optional

def setup_directories(input_dir: str = "input_images", output_dir: str = "output_images") -> None:
    """Create input and output directories if they don't exist"""
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

def clear_directory(directory: str) -> None:
    """Clear all files from a directory"""
    if os.path.exists(directory):
        for file in os.listdir(directory):
            file_path = os.path.join(directory, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")
    else:
        os.makedirs(directory, exist_ok=True)

def clear_all_data(input_dir: str = "input_images", output_dir: str = "output_images", result_file: str = "result.json") -> None:
    """Clear all data folders and files"""
    try:
        # Clear input directory
        clear_directory(input_dir)
        
        # Clear output directory
        clear_directory(output_dir)
        
        # Remove result file if it exists
        if os.path.exists(result_file):
            os.remove(result_file)
            
        # Remove node mappings file if it exists
        node_mappings_file = "node_mappings.json"
        if os.path.exists(node_mappings_file):
            os.remove(node_mappings_file)
            
    except Exception as e:
        print(f"Error during cleanup: {e}")
        # Ensure directories exist even if cleanup fails
        setup_directories(input_dir, output_dir) 