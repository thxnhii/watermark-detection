import os
import json
import requests
import shutil
from typing import List, Dict, Set
import asyncio
import aiohttp
import ssl
import certifi
import streamlit as st
from watermark_detection import run_inference as detect_watermarks
from utils import setup_directories, clear_directory

class FigmaPipeline:
    def __init__(self, figma_file_key: str, figma_access_token: str, batch_size: int = 10, debug_mode: bool = False):
        self.figma_file_key = figma_file_key
        self.figma_access_token = figma_access_token
        self.batch_size = batch_size
        self.debug_mode = debug_mode
        self.input_dir = "input_images"
        self.output_dir = "output_images"
        self.mapping_file = "node_mappings.json"  # File to store node mappings

        setup_directories(self.input_dir, self.output_dir)

        # Configure SSL context
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

        if self.debug_mode:
            st.info("Pipeline Initialization:")
            st.json({
                "File Key": self.figma_file_key,
                "Batch Size": self.batch_size,
                "Input Directory": self.input_dir,
                "Output Directory": self.output_dir
            })
        else:
            print(f"Initialized FigmaPipeline with:")
            print(f"- File Key: {self.figma_file_key}")
            print(f"- Batch Size: {self.batch_size}")
            print(f"- Input Directory: {self.input_dir}")
            print(f"- Output Directory: {self.output_dir}")

    def _log(self, message: str, level: str = "info"):
        """Helper method to log messages either to console or UI based on debug mode"""
        if self.debug_mode:
            if level == "info":
                st.info(message)
            elif level == "success":
                st.success(message)
            elif level == "error":
                st.error(message)
            else:
                st.text(message)
        else:
            print(message)

    def _clear_input_directory(self):
        """Clear all files from the input directory"""
        clear_directory(self.input_dir)

    def _get_image_url(self, image_ref: str) -> str:
        """Create Figma image URL from imageRef"""
        return f"https://www.figma.com/file/{self.figma_file_key}/image/{image_ref}"

    async def _download_image(self, session: aiohttp.ClientSession, image_ref: str) -> str:
        """Download a single image asynchronously"""
        try:
            image_url = self._get_image_url(image_ref)
            self._log(f"Attempting to download image from URL: {image_url}")

            # Add comprehensive headers to mimic browser request
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": f"https://www.figma.com/file/{self.figma_file_key}/",
                "Sec-Fetch-Dest": "image",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "same-origin",
                "Connection": "keep-alive",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache"
            }

            self._log(f"Using headers: {headers}")

            # First request to get the redirect URL
            async with session.get(
                image_url, 
                headers=headers, 
                ssl=self.ssl_context,
                allow_redirects=False,
                timeout=30
            ) as response:
                if response.status in (301, 302, 303, 307, 308):
                    # Get the S3 URL from the Location header
                    s3_url = response.headers['Location']
                    self._log(f"Redirected to S3 URL: {s3_url}")

                    # Now download from the S3 URL with the same headers
                    async with session.get(
                        s3_url, 
                        headers=headers, 
                        ssl=self.ssl_context,
                        timeout=30
                    ) as s3_response:
                        if s3_response.status == 200:
                            filepath = os.path.join(self.input_dir, f"{image_ref}.png")
                            with open(filepath, 'wb') as f:
                                f.write(await s3_response.read())
                            self._log(f"Successfully downloaded to: {filepath}", "success")
                            self._log(f"File size: {os.path.getsize(filepath)} bytes")
                            return filepath
                        else:
                            self._log(f"Failed to download from S3: {s3_response.status}", "error")
                            self._log(f"Response headers: {s3_response.headers}")
                            return None
                else:
                    self._log(f"Failed to get redirect URL: {response.status}", "error")
                    self._log(f"Response headers: {response.headers}")
                    return None
        except Exception as e:
            self._log(f"Error downloading image {image_ref}: {str(e)}", "error")
            import traceback
            self._log(f"Traceback: {traceback.format_exc()}")
            return None

    async def _process_batch(self, image_refs: List[str], batch_num: int) -> List[str]:
        """Process a batch of images asynchronously"""
        connector = aiohttp.TCPConnector(ssl=self.ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for image_ref in image_refs:
                self._log(f"Downloading image {image_ref} from batch {batch_num}")
                task = self._download_image(session, image_ref)
                tasks.append(task)

            downloaded_paths = await asyncio.gather(*tasks)
            successful_downloads = [path for path in downloaded_paths if path is not None]
            
            # Log batch processing results
            self._log(f"\nBatch {batch_num} Processing Results:", "info")
            self._log(f"Total images in batch: {len(image_refs)}")
            self._log(f"Successfully downloaded: {len(successful_downloads)}")
            self._log(f"Failed downloads: {len(image_refs) - len(successful_downloads)}")
            
            if successful_downloads:
                self._log("\nSuccessfully processed images:")
                for idx, path in enumerate(successful_downloads, 1):
                    file_size = os.path.getsize(path)
                    file_name = os.path.basename(path)
                    self._log(f"{idx}. {file_name} ({file_size/1024:.2f} KB)")
            
            if len(image_refs) - len(successful_downloads) > 0:
                self._log("\nFailed images:", "error")
                for idx, (ref, path) in enumerate(zip(image_refs, downloaded_paths), 1):
                    if path is None:
                        self._log(f"{idx}. {ref}", "error")
            
            return successful_downloads

    def _get_figma_images(self) -> List[str]:
        """Get image refs from Figma file"""
        headers = {
            "X-Figma-Token": self.figma_access_token
        }

        self._log("Fetching Figma file data...")

        # First get the file data to get node IDs
        file_url = f"https://api.figma.com/v1/files/{self.figma_file_key}"
        self._log(f"Fetching file data from: {file_url}")

        # Configure requests session with SSL verification disabled
        session = requests.Session()
        session.verify = False
        file_response = session.get(file_url, headers=headers)

        if file_response.status_code != 200:
            self._log(f"Failed to get Figma file: {file_response.status_code}", "error")
            self._log(f"Response content: {file_response.text}")
            raise Exception(f"Failed to get Figma file: {file_response.status_code} - {file_response.text}")

        # Get all image nodes from the file
        data = file_response.json()
        image_refs = set()  # Use a set to automatically remove duplicates
        image_to_nodes_map = {}  # Dictionary to store imageRef to node IDs mapping

        def extract_image_nodes(node, path=""):
            current_path = f"{path}/{node.get('name', 'unnamed')}"
            self._log(f"Checking node: {current_path} (type: {node.get('type')})")

            # Check if this node is an image or contains images
            if node.get('type') in ['FRAME', 'COMPONENT', 'INSTANCE', 'IMAGE', 'RECTANGLE']:
                if node.get('fills'):
                    for fill in node.get('fills', []):
                        if fill.get('type') == 'IMAGE':
                            self._log(f"Found image node: {current_path}")
                            if self.debug_mode:
                                st.json(fill)
                            else:
                                print(f"Fill data: {fill}")
                            if 'imageRef' in fill:
                                image_ref = fill['imageRef']
                                image_refs.add(image_ref)
                                
                                # Store node information for this imageRef
                                if image_ref not in image_to_nodes_map:
                                    image_to_nodes_map[image_ref] = []
                                
                                image_to_nodes_map[image_ref].append({
                                    'node_id': node['id'],
                                    'name': node.get('name', 'unnamed'),
                                    'path': current_path
                                })
                            break

            # Recursively check children
            if 'children' in node:
                for child in node['children']:
                    extract_image_nodes(child, current_path)

        self._log("Starting node extraction...")
        extract_image_nodes(data['document'])

        # Save the mappings to a JSON file
        try:
            with open(self.mapping_file, 'w') as f:
                json.dump(image_to_nodes_map, f, indent=2)
            self._log(f"Successfully saved node mappings to {self.mapping_file}", "success")
        except Exception as e:
            self._log(f"Error saving node mappings: {str(e)}", "error")

        # Log the mappings
        if self.debug_mode:
            st.json(image_to_nodes_map)
        else:
            print("\nImage to Node Mappings:")
            for image_ref, nodes in image_to_nodes_map.items():
                print(f"\nImageRef: {image_ref}")
                for node in nodes:
                    print(f"  Node ID: {node['node_id']}")
                    print(f"  Name: {node['name']}")
                    print(f"  Path: {node['path']}")

        # Convert set to list
        unique_refs = list(image_refs)
        self._log(f"Found {len(unique_refs)} unique images", "success")
        self._log("Image refs to be downloaded:")
        for idx, ref in enumerate(unique_refs, 1):
            self._log(f"{idx}. {ref}")

        return unique_refs

    async def run_pipeline(self):
        """Run the complete pipeline"""
        try:
            self._log("Starting pipeline execution...")
            self._log(f"Current working directory: {os.getcwd()}")
            self._log(f"Input directory exists: {os.path.exists(self.input_dir)}")
            self._log(f"Output directory exists: {os.path.exists(self.output_dir)}")

            # Get all image refs from Figma
            image_refs = self._get_figma_images()
            total_images = len(image_refs)
            self._log(f"Total images to process: {total_images}", "info")

            # Calculate total number of batches
            total_batches = (len(image_refs) + self.batch_size - 1) // self.batch_size
            
            # Create progress bar (always show in both modes)
            progress_bar = st.progress(0)
            status_text = st.empty()

            # Process images in batches
            successful_batches = 0
            total_processed = 0
            total_failed = 0

            for i in range(0, len(image_refs), self.batch_size):
                batch = image_refs[i:i + self.batch_size]
                batch_num = i//self.batch_size + 1
                
                # Update progress bar (always show in both modes)
                current_progress = batch_num / total_batches
                progress_bar.progress(current_progress)
                status_text.text(f"Processing batch {batch_num}/{total_batches}")

                # Only show detailed debug info in debug mode
                if self.debug_mode:
                    self._log(f"\nProcessing batch {batch_num}", "info")
                    self._log(f"Batch size: {len(batch)}")
                    self._log(f"Batch items: {batch}")

                # Download batch of images
                downloaded_paths = await self._process_batch(batch, batch_num)

                if downloaded_paths:
                    if self.debug_mode:
                        self._log(f"Running watermark detection on {len(downloaded_paths)} images")
                        self._log(f"Image paths: {downloaded_paths}")
                    
                    # Run inference on the batch
                    detect_watermarks(downloaded_paths, batch)

                    # Count only successfully processed images from result.json
                    if os.path.exists("result.json"):
                        with open("result.json", "r") as f:
                            results = json.load(f)
                            processed_in_batch = sum(1 for r in results if r["imageRef"] in batch)
                            total_processed += processed_in_batch
                            total_failed += len(batch) - processed_in_batch
                            successful_batches += 1

                if self.debug_mode:
                    self._log(f"Completed batch {batch_num}", "success")

            # Log final processing summary
            self._log("\nPipeline Processing Summary:", "info")
            self._log(f"Total images: {total_images}")
            self._log(f"Successfully processed: {total_processed}")
            self._log(f"Failed to process: {total_failed}")
            self._log(f"Success rate: {(total_processed/total_images)*100:.2f}%")
            self._log(f"Total batches: {total_batches}")
            self._log(f"Successful batches: {successful_batches}")

            # Clear progress bar after completion
            progress_bar.empty()
            status_text.empty()

        except Exception as e:
            self._log(f"Pipeline error: {str(e)}", "error")
            import traceback
            self._log(f"Traceback: {traceback.format_exc()}")
            st.error(f"Pipeline error: {e}")


async def main():
    # Replace these with your actual Figma credentials
    FIGMA_FILE_KEY = "your_figma_file_key"
    FIGMA_ACCESS_TOKEN = "your_figma_access_token"

    pipeline = FigmaPipeline(
        figma_file_key=FIGMA_FILE_KEY,
        figma_access_token=FIGMA_ACCESS_TOKEN,
        batch_size=10
    )

    await pipeline.run_pipeline()

if __name__ == "__main__":
    asyncio.run(main()) 