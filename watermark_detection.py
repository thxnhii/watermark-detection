from ultralytics import YOLO
import os
import json
from PIL import Image, ImageDraw
import traceback

model_path = 'watermarks.pt'
INPUT_DIR = "input_images"
OUTPUT_DIR = "output_images"

model = YOLO(model_path)

def image_enhancer(image_path):
    try:
        image = Image.open(image_path)
        if image.mode != 'RGBA':
            image = image.convert("RGBA")
        return image
    except Exception as e:
        print(f"Error enhancing image {image_path}: {str(e)}")
        return None

def run_inference(image_paths: list, image_refs: list):
    try:
        # Ensure output directory exists
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Process images
        watermark_status = []
        for idx, (image_path, image_ref) in enumerate(zip(image_paths, image_refs)):
            try:
                # Enhance image
                image = image_enhancer(image_path)
                if image is None:
                    print(f"Skipping image {image_ref} due to enhancement error")
                    continue

                # Run prediction
                result = model.predict(image, conf=0.1, iou=0.)[0]
                
                # Create output path using imageRef
                output_filename = f"{image_ref}.png"
                output_path = os.path.join(OUTPUT_DIR, output_filename)
                
                # Process result
                if len(result.boxes) > 0:
                    watermark_status.append({
                        "image": output_path,
                        "status": True,
                        "imageRef": image_ref
                    })
                    # Draw boxes for watermarks
                    draw = ImageDraw.Draw(image)
                    for box in result.boxes:
                        coordinates = box.xyxy.tolist()
                        draw.rectangle(coordinates[0], outline="red", width=3)
                else:
                    watermark_status.append({
                        "image": output_path,
                        "status": False,
                        "imageRef": image_ref
                    })
                
                # Save the image
                image.save(output_path)
                print(f"Successfully processed image {image_ref}")

            except Exception as e:
                print(f"Error processing image {image_ref}: {str(e)}")
                print(traceback.format_exc())
                continue

        # Load existing results if file exists
        existing_results = []
        if os.path.exists("result.json"):
            try:
                with open("result.json", "r", encoding='utf-8') as f:
                    existing_results = json.load(f)
            except json.JSONDecodeError:
                print("Error reading existing result.json, starting fresh")
                existing_results = []

        # Filter out any existing results with the same imageRef
        existing_refs = {result.get("imageRef") for result in existing_results if isinstance(result, dict) and "imageRef" in result}
        unique_new_results = [result for result in watermark_status if result["imageRef"] not in existing_refs]

        # Append new results
        all_results = existing_results + unique_new_results

        # Save combined results
        with open("result.json", "w", encoding='utf-8') as f:
            json.dump(all_results, f, indent=4)
            
        print(f"Successfully processed {len(watermark_status)} images")
        print(f"Added {len(unique_new_results)} new results to result.json")

    except Exception as e:
        print(f"Error in run_inference: {str(e)}")
        print(traceback.format_exc())