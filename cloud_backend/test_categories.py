import boto3
import io
import json
from PIL import Image

def main():
    s3 = boto3.client('s3', region_name='us-east-1')
    rekognition = boto3.client('rekognition', region_name='us-east-1')
    
    bucket = 'woods-net-storage'
    key = 'woods-net/mules/MULE05/0A0038_IMAG0009.AVIF' # Known image with a person, chairs, interior design
    
    print(f"Downloading {key}...")
    img_obj = s3.get_object(Bucket=bucket, Key=key)
    img_bytes = img_obj['Body'].read()
    
    image = Image.open(io.BytesIO(img_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")
        
    jpeg_io = io.BytesIO()
    image.save(jpeg_io, format="JPEG", quality=85)
    jpeg_bytes = jpeg_io.getvalue()
    
    print("Calling Rekognition...")
    response = rekognition.detect_labels(
        Image={'Bytes': jpeg_bytes},
        MaxLabels=20, # Increased slightly to see more categories
        MinConfidence=75
    )
    
    print("\n--- Rekognition Response ---")
    for label in response.get('Labels', []):
        name = label['Name']
        confidence = label['Confidence']
        categories = [cat['Name'] for cat in label.get('Categories', [])]
        print(f"Label: {name} (Conf: {confidence:.2f}%) | Categories: {categories}")

if __name__ == '__main__':
    main()
