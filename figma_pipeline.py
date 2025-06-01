import os
import json
import requests
import shutil
from typing import List, Dict, Set
import asyncio
import aiohttp
import ssl
import certifi
from watermark_detection import run_inference as detect_watermarks

class FigmaPipeline:
    def __init__(self, figma_file_key: str, figma_access_token: str, batch_size: int = 10):
        self.figma_file_key = figma_file_key
        self.figma_access_token = figma_access_token
        self.batch_size = batch_size
        self.input_dir = "input_images"
        self.output_dir = "output_images"
        self._setup_directories()
        
        # Configure SSL context
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    def _setup_directories(self):
        """Create input and output directories if they don't exist"""
        os.makedirs(self.input_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def _clear_input_directory(self):
        """Clear all files from the input directory"""
        for filename in os.listdir(self.input_dir):
            file_path = os.path.join(self.input_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")

    def _get_image_url(self, image_ref: str) -> str:
        """Create Figma image URL from imageRef"""
        return f"https://www.figma.com/file/{self.figma_file_key}/image/{image_ref}"

    async def _download_image(self, session: aiohttp.ClientSession, image_ref: str) -> str:
        """Download a single image asynchronously"""
        try:
            image_url = self._get_image_url(image_ref)
            
            # Add headers to mimic browser request
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"https://www.figma.com/file/{self.figma_file_key}/"
            }
            
            # First request to get the redirect URL
            async with session.get(image_url, headers=headers, ssl=self.ssl_context, allow_redirects=False) as response:
                if response.status in (301, 302, 303, 307, 308):
                    # Get the S3 URL from the Location header
                    s3_url = response.headers['Location']
                    print(f"Redirected to S3 URL: {s3_url}")
                    
                    # Now download from the S3 URL
                    async with session.get(s3_url, headers=headers, ssl=self.ssl_context) as s3_response:
                        if s3_response.status == 200:
                            filepath = os.path.join(self.input_dir, f"{image_ref}.png")
                            with open(filepath, 'wb') as f:
                                f.write(await s3_response.read())
                            print(f"Successfully downloaded to: {filepath}")
                            return filepath
                        else:
                            print(f"Failed to download from S3: {s3_response.status}")
                            return None
                else:
                    print(f"Failed to get redirect URL: {response.status}")
                    return None
        except Exception as e:
            print(f"Error downloading image {image_ref}: {e}")
            return None

    async def _process_batch(self, image_refs: List[str], batch_num: int) -> List[str]:
        """Process a batch of images asynchronously"""
        connector = aiohttp.TCPConnector(ssl=self.ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for image_ref in image_refs:
                print(f"\nDownloading image {image_ref} from batch {batch_num}")
                task = self._download_image(session, image_ref)
                tasks.append(task)
            
            downloaded_paths = await asyncio.gather(*tasks)
            successful_downloads = [path for path in downloaded_paths if path is not None]
            print(f"\nSuccessfully downloaded {len(successful_downloads)}/{len(image_refs)} images in batch {batch_num}")
            return successful_downloads

    def _get_figma_images(self) -> List[str]:
        """Get image refs from Figma file"""
        headers = {
            "X-Figma-Token": self.figma_access_token
        }
        
        # First get the file data to get node IDs
        file_url = f"https://api.figma.com/v1/files/{self.figma_file_key}"
        print(f"Fetching file data from: {file_url}")
        
        # Configure requests session with SSL verification disabled
        session = requests.Session()
        session.verify = False
        file_response = session.get(file_url, headers=headers)
        
        if file_response.status_code != 200:
            raise Exception(f"Failed to get Figma file: {file_response.status_code} - {file_response.text}")
        
        # Get all image nodes from the file
        data = file_response.json()
        image_refs = set()  # Use a set to automatically remove duplicates
        
        def extract_image_nodes(node, path=""):
            current_path = f"{path}/{node.get('name', 'unnamed')}"
            print(f"Checking node: {current_path} (type: {node.get('type')})")
            
            # Check if this node is an image or contains images
            if node.get('type') in ['FRAME', 'COMPONENT', 'INSTANCE', 'IMAGE', 'RECTANGLE']:
                if node.get('fills'):
                    for fill in node.get('fills', []):
                        if fill.get('type') == 'IMAGE':
                            print(f"Found image node: {current_path}")
                            if 'imageRef' in fill:
                                image_refs.add(fill['imageRef'])
                            break
            
            # Recursively check children
            if 'children' in node:
                for child in node['children']:
                    extract_image_nodes(child, current_path)
        
        print("\nStarting node extraction...")
        extract_image_nodes(data['document'])
        
        # Convert set to list
        unique_refs = list(image_refs)
        print(f"\nFound {len(unique_refs)} unique images")
        
        # Print all image refs in debug mode
        print("\nImage refs to be downloaded:")
        for idx, ref in enumerate(unique_refs, 1):
            print(f"{idx}. {ref}")
        
        return unique_refs

    async def run_pipeline(self):
        """Run the complete pipeline"""
        try:
            # Get all image refs from Figma
            image_refs = self._get_figma_images()
            
            # Process images in batches
            for i in range(0, len(image_refs), self.batch_size):
                batch = image_refs[i:i + self.batch_size]
                print(f"Processing batch {i//self.batch_size + 1}")
                
                # Download batch of images
                downloaded_paths = await self._process_batch(batch, i//self.batch_size + 1)
                
                if downloaded_paths:
                    # Run inference on the batch
                    detect_watermarks(downloaded_paths, batch)
                    
                    # Clear input directory after processing
                    self._clear_input_directory()
                
                print(f"Completed batch {i//self.batch_size + 1}")
                
        except Exception as e:
            print(f"Pipeline error: {e}")

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