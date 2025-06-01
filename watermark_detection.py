from ultralytics import YOLO
import os
import json
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw

model_path = 'watermarks.pt'
INPUT_DIR = "input_images"
OUTPUT_DIR = "output_images"

model = YOLO(model_path)

def image_enhancer(image_path, threshold=70):
	image = Image.open(image_path).convert("RGB")
	gray_image = image.convert("L")
	enhancer = ImageEnhance.Contrast(gray_image)
	contrast_image = enhancer.enhance(0.85)
	sharpened_image = contrast_image.filter(ImageFilter.EDGE_ENHANCE_MORE)
	sharpened_image = sharpened_image.point(lambda x: x if x > threshold else 0)
	return sharpened_image.convert("RGB")

def run_inference(image_paths: list, image_refs: list):
    try:
        # Ensure output directory exists
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Process images
        images = [Image.open(image_path) for image_path in image_paths]
        results = [model.predict(image, conf=0.1, iou=0.) for image in images]
        
        watermark_status = []
        for idx, (result, image_ref) in enumerate(zip(results, image_refs)):
            result = result[0]
            image = Image.open(image_paths[idx])
            
            # Create output path using imageRef
            output_filename = f"{image_ref}.png"
            output_path = os.path.join(OUTPUT_DIR, output_filename)
            
            if len(result.boxes) > 0:
                watermark_status.append(
                    {
                        "image": output_path,
                        "status": True,
                        "imageRef": image_ref
                    }
                )
                for box in result.boxes:
                    coordinates = box.xyxy.tolist()
                    draw = ImageDraw.Draw(image)
                    draw.rectangle(coordinates[0], outline="red", width=3)
                image.save(output_path)
            else:
                watermark_status.append(
                    {
                        "image": output_path,
                        "status": False,
                        "imageRef": image_ref
                    }
                )
                image.save(output_path)

        # Load existing results if file exists
        existing_results = []
        if os.path.exists("result.json"):
            try:
                with open("result.json", "r", encoding='utf-8') as f:
                    existing_results = json.load(f)
            except json.JSONDecodeError:
                existing_results = []

        # Filter out any existing results with the same imageRef
        existing_refs = {result.get("imageRef") for result in existing_results if isinstance(result, dict) and "imageRef" in result}
        unique_new_results = [result for result in watermark_status if result["imageRef"] not in existing_refs]

        # Append new results
        all_results = existing_results + unique_new_results

        # Save combined results
        with open("result.json", "w", encoding='utf-8') as f:
            json.dump(all_results, f, indent=4)

    except Exception as e:
        print(e)
