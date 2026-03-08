import boto3
import os
import argparse
from pathlib import Path

def upload_test_images(bucket_name, image_dir, mule_id="TEST_01"):
    """
    Manually uploads legacy images to the Woods-Net S3 bucket to trigger the AI pipeline.
    Expects AVIF format for the AI lambda trigger.
    """
    s3 = boto3.client('s3')
    
    img_path = Path(image_dir)
    if not img_path.exists() or not img_path.is_dir():
        print(f"Error: Directory '{image_dir}' not found.")
        return

    # S3 trigger is configured for .avif files
    images = list(img_path.glob("*.avif"))
    
    if not images:
        print(f"No .avif images found in '{image_dir}'. Conversion required.")
        return
        
    print(f"Found {len(images)} .avif images. Uploading as Mule ID: {mule_id}...\n")
    
    success_count = 0
    for img in images:
        s3_key = f"woods-net/mules/{mule_id}/{img.name}"
        try:
            print(f"Uploading: {img.name} -> s3://{bucket_name}/{s3_key}")
            # The lambda trigger listens for 's3:ObjectCreated:Put'
            s3.upload_file(str(img), bucket_name, s3_key)
            success_count += 1
        except Exception as e:
            print(f"Failed to upload {img.name}: {e}")
            
    print(f"\nDone. Successfully injected {success_count}/{len(images)} images into the AI pipeline.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Inject test images into Woods-Net S3 bucket.")
    parser.add_argument('--bucket', required=True, help="Your deployed Woods-Net S3 bucket name")
    parser.add_argument('--dir', required=True, help="Local directory containing legacy .avif images")
    parser.add_argument('--mule', default="TEST_01", help="Virtual Mule ID to assign these images to")
    
    args = parser.parse_args()
    upload_test_images(args.bucket, args.dir, args.mule)
