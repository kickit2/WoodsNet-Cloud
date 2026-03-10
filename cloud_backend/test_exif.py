import io
from PIL import Image
from PIL.ExifTags import TAGS
import pillow_heif
import boto3

pillow_heif.register_heif_opener()

def main():
    s3 = boto3.client('s3', region_name='us-east-1')
    bucket = 'woods-net-storage'
    key = 'woods-net/mules/MULE05/0A0038_IMAG0009.AVIF' 
    
    print(f"Downloading {key}...")
    img_obj = s3.get_object(Bucket=bucket, Key=key)
    img_bytes = img_obj['Body'].read()
    
    image = Image.open(io.BytesIO(img_bytes))
    
    # Method 1
    exif1 = image.getexif()
    print("--- Method 1: image.getexif() ---")
    if exif1:
        for k, v in exif1.items():
            name = TAGS.get(k, k)
            print(f"{name} ({k}): {v}")
    
    # Method 2: IFD format
    print("\n--- Method 2: IFD Exif ---")
    if exif1:
        ifd = exif1.get_ifd(0x8769) # ExifOffset ID
        for k, v in ifd.items():
            name = TAGS.get(k, k)
            print(f"{name} ({k}): {v}")
            
    # Method 3: Raw info
    print("\n--- Method 3: raw image.info ---")
    for k, v in image.info.items():
        if k == 'exif':
            print(f"exif: <bytes length {len(v)}>")
        else:
            print(f"{k}: {v}")

if __name__ == '__main__':
    main()
