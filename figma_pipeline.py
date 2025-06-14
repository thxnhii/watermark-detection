import os
import json
import requests
from typing import List
import asyncio
import aiohttp
import ssl
import certifi
import streamlit as st
from watermark_detection import run_inference as detect_watermarks
from utils import setup_directories, clear_directory
from aiohttp import ClientSession, TCPConnector
from aiohttp.client_exceptions import ClientResponseError

try:
    from fake_useragent import UserAgent
    ua = UserAgent()
    USE_FAKE_USERAGENT = True
except ImportError:
    USE_FAKE_USERAGENT = False

class FigmaPipeline:
    def __init__(self, figma_file_key: str, figma_access_token: str, batch_size: int = 10, debug_mode: bool = False):
        self.figma_file_key = figma_file_key
        self.figma_access_token = figma_access_token
        self.batch_size = batch_size
        self.debug_mode = debug_mode
        self.input_dir = "input_images"
        self.output_dir = "output_images"
        self.mapping_file = "node_mappings.json"

        setup_directories(self.input_dir, self.output_dir)

        # Configure SSL context with proper verification
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

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
        if self.debug_mode:
            if level == "info":
                st.info(message)
            elif level == "success":
                st.success(message)
            elif level == "error":
                st.error(message)
            elif level == "warning":
                st.warning(message)
            else:
                st.text(message)
        else:
            print(message)

    def _clear_input_directory(self):
        clear_directory(self.input_dir)

    def _get_image_url(self, image_ref: str) -> str:
        return f"https://www.figma.com/file/{self.figma_file_key}/image/{image_ref}"

    def _get_file_extension(self, content_type: str) -> str:
        """Determine file extension based on Content-Type"""
        content_type = content_type.lower()
        if "image/png" in content_type:
            return ".png"
        elif "image/jpeg" in content_type or "image/jpg" in content_type:
            return ".jpg"
        elif "image/webp" in content_type:
            return ".webp"
        return ".png"  # Default to PNG if unknown

    async def _download_image(self, session: ClientSession, image_ref: str, retries: int = 3) -> str:
        """
        Download a single image asynchronously from a Figma image URL, following redirects to the final image.
        Mimics browser behavior with appropriate headers and handles Figma access token for private files.
        """
        image_url = self._get_image_url(image_ref)
        self._log(f"Downloading image: {image_ref}")

        # Browser-mimicking headers
        headers = {
            "User-Agent": ua.chrome if USE_FAKE_USERAGENT else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": f"https://www.figma.com/file/{self.figma_file_key}/",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }
        if self.figma_access_token:
            headers["X-Figma-Token"] = self.figma_access_token

        attempt = 0
        while attempt < retries:
            attempt += 1
            try:
                async with session.get(
                    image_url,
                    headers=headers,
                    ssl=self.ssl_context,
                    timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_read=30),
                    allow_redirects=True
                ) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "")
                        if "image" not in content_type.lower():
                            self._log(f"Response is not an image (Content-Type: {content_type})", "error")
                            return None

                        extension = self._get_file_extension(content_type)
                        filepath = os.path.join(self.input_dir, f"{image_ref}{extension}")
                        content = await response.read()
                        with open(filepath, 'wb') as f:
                            f.write(content)
                        file_size = os.path.getsize(filepath)
                        self._log(f"Downloaded: {filepath} ({file_size/1024:.2f} KB)", "success")
                        return filepath
                    else:
                        try:
                            error_text = await response.text()
                            self._log(f"Error response (status {response.status}): {error_text}", "error")
                        except:
                            self._log(f"Error response (status {response.status}): Unable to read body", "error")
                        raise ClientResponseError(response.request_info, response.history, status=response.status, message=response.reason)

            except ClientResponseError as e:
                if e.status in (403, 429, 503, 502):
                    delay = 2 ** attempt * 2
                    self._log(f"Retryable error (status {e.status}: {e.message}), retrying after {delay}s", "warning")
                    await asyncio.sleep(delay)
                    continue
                self._log(f"HTTP error: {str(e)}", "error")
                return None
            except Exception as e:
                self._log(f"Error downloading {image_ref}: {str(e)}", "error")
                return None

        self._log(f"Failed to download {image_ref} after {retries} attempts", "error")
        return None

    async def _process_batch(self, image_refs: List[str], batch_num: int) -> List[str]:
        connector = TCPConnector(ssl=self.ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for image_ref in image_refs:
                self._log(f"Downloading image {image_ref} from batch {batch_num}")
                task = self._download_image(session, image_ref)
                tasks.append(task)

            downloaded_paths = await asyncio.gather(*tasks)
            successful_downloads = [path for path in downloaded_paths if path is not None]
            
            self._log(f"\nBatch {batch_num} Processing Results:", "info")
            self._log(f"Total images in batch: {len(image_refs)}")
            self._log(f"Successfully downloaded: {len(successful_downloads)}")
            self._log(f"Failed downloads: {len(image_refs) - len(successful_downloads)}")
            
            if successful_downloads:
                for path in successful_downloads:
                    file_size = os.path.getsize(path)
                    self._log(f"- {os.path.basename(path)} ({file_size/1024:.2f} KB)")
            if len(image_refs) - len(successful_downloads) > 0:
                self._log("Failed images:", "error")
                for ref, path in zip(image_refs, downloaded_paths):
                    if path is None:
                        self._log(f"- {ref}", "error")
            
            return successful_downloads

    def _get_figma_images(self) -> List[str]:
        headers = {
            "X-Figma-Token": self.figma_access_token
        }

        self._log("Fetching Figma file data...")
        file_url = f"https://api.figma.com/v1/files/{self.figma_file_key}"
        self._log(f"Fetching file data from: {file_url}")

        session = requests.Session()
        session.verify = False
        file_response = session.get(file_url, headers=headers)

        if file_response.status_code != 200:
            self._log(f"Failed to get Figma file: {file_response.status_code}", "error")
            self._log(f"Response content: {file_response.text}")
            raise Exception(f"Failed to get Figma file: {file_response.status_code} - {file_response.text}")

        data = file_response.json()
        image_refs = set()
        image_to_nodes_map = {}

        def extract_image_nodes(node, path=""):
            current_path = f"{path}/{node.get('name', 'unnamed')}"
            self._log(f"Checking node: {current_path} (type: {node.get('type')})")

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
                                
                                if image_ref not in image_to_nodes_map:
                                    image_to_nodes_map[image_ref] = []
                                
                                image_to_nodes_map[image_ref].append({
                                    'node_id': node['id'],
                                    'name': node.get('name', 'unnamed'),
                                    'path': current_path
                                })
                            break

            if 'children' in node:
                for child in node['children']:
                    extract_image_nodes(child, current_path)

        self._log("Extracting image nodes...")
        extract_image_nodes(data['document'])

        try:
            with open(self.mapping_file, 'w') as f:
                json.dump(image_to_nodes_map, f, indent=2)
            self._log(f"Successfully saved node mappings to {self.mapping_file}", "success")
        except Exception as e:
            self._log(f"Error saving node mappings: {str(e)}", "error")

        if self.debug_mode:
            st.json(image_to_nodes_map)
        else:
            print("\nImage to Node Mappings:")
            for image_ref, nodes in image_to_nodes_map.items():
                print(f"\nImageRef: {image_ref}")
                for node in nodes:
                    print(f"  Node ID: {node['node_id']}, Name: {node['name']}, Path: {node['path']}")

        unique_refs = list(image_refs)
        self._log(f"Found {len(unique_refs)} unique images", "success")
        self._log("Image refs to be downloaded:")
        for idx, ref in enumerate(unique_refs, 1):
            self._log(f"{idx}. {ref}")

        return unique_refs

    async def run_pipeline(self):
        try:
            self._log("Starting pipeline execution...")
            self._log(f"Current working directory: {os.getcwd()}")
            self._log(f"Input directory exists: {os.path.exists(self.input_dir)}")
            self._log(f"Output directory exists: {os.path.exists(self.output_dir)}")

            image_refs = self._get_figma_images()
            total_images = len(image_refs)
            self._log(f"Total images to process: {total_images}", "info")

            total_batches = (len(image_refs) + self.batch_size - 1) // self.batch_size
            
            progress_bar = st.progress(0)
            status_text = st.empty()

            successful_batches = 0
            total_processed = 0
            total_failed = 0

            for i in range(0, len(image_refs), self.batch_size):
                batch = image_refs[i:i + self.batch_size]
                batch_num = i // self.batch_size + 1
                
                progress_bar.progress(batch_num / total_batches)
                status_text.text(f"Processing batch {batch_num}/{total_batches}")

                if self.debug_mode:
                    self._log(f"\nProcessing batch {batch_num}", "info")
                    self._log(f"Batch size: {len(batch)}")
                    self._log(f"Batch items: {batch}")

                downloaded_paths = await self._process_batch(batch, batch_num)

                if downloaded_paths:
                    if self.debug_mode:
                        self._log(f"Running watermark detection on {len(downloaded_paths)} images")
                        self._log(f"Image paths: {downloaded_paths}")
                    
                    detect_watermarks(downloaded_paths, batch)

                    if os.path.exists("result.json"):
                        with open("result.json", "r") as f:
                            results = json.load(f)
                            processed_in_batch = sum(1 for r in results if r["imageRef"] in batch)
                            total_processed += processed_in_batch
                            total_failed += len(batch) - processed_in_batch
                            successful_batches += 1

                if self.debug_mode:
                    self._log(f"Completed batch {batch_num}", "success")

            self._log("\nPipeline Processing Summary:", "info")
            self._log(f"Total images: {total_images}")
            self._log(f"Successfully processed: {total_processed}")
            self._log(f"Failed to process: {total_failed}")
            self._log(f"Success rate: {(total_processed/total_images)*100:.2f}%")
            self._log(f"Total batches: {total_batches}")
            self._log(f"Successful batches: {successful_batches}")

            progress_bar.empty()
            status_text.empty()

        except Exception as e:
            self._log(f"Pipeline error: {str(e)}", "error")
            import traceback
            self._log(f"Traceback: {traceback.format_exc()}")
            st.error(f"Pipeline error: {e}")

async def main():
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