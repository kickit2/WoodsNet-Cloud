import boto3
import json

def main():
    s3 = boto3.client('s3', region_name='us-east-1')
    lam = boto3.client('lambda', region_name='us-east-1')
    
    bucket = 'woods-net-storage'
    prefix = 'woods-net/cameras/'
    
    print(f"Scanning bucket {bucket} for objects in {prefix}...")
    
    paginator = s3.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
    
    count = 0
    for page in pages:
        if 'Contents' not in page:
            continue
        for obj in page['Contents']:
            key = obj['Key']
            if key.lower().endswith('.avif'):
                count += 1
                
                # Construct synthetic S3 Put event
                payload = {
                    "Records": [
                        {
                            "eventName": "ObjectCreated:Put",
                            "s3": {
                                "bucket": {"name": bucket},
                                "object": {"key": key}
                            }
                        }
                    ]
                }
                
                print(f"Triggering AI for: {key}")
                try:
                    response = lam.invoke(
                        FunctionName='WoodsNetAnalyzeImage',
                        InvocationType='RequestResponse',
                        Payload=json.dumps(payload)
                    )
                    
                    res_payload = response['Payload'].read().decode('utf-8')
                    print(f"  -> Response: {res_payload}")
                except Exception as e:
                    print(f"  -> Error: {e}")
                    
    print(f"\\nDone! Triggered AI for {count} images.")

if __name__ == '__main__':
    main()
