import boto3

def main():
    dynamo = boto3.client('dynamodb', region_name='us-east-1')
    table = 'WoodsNetImageTags'
    
    print(f"Scanning {table} for existing items...")
    paginator = dynamo.get_paginator('scan')
    pages = paginator.paginate(TableName=table)
    
    count = 0
    for page in pages:
        for item in page.get('Items', []):
            key = item['ImageKey']['S']
            
            # Don't delete the Mule telemetry state records, only the image tags
            if key.startswith('MULE_STATE#'):
                continue
                
            dynamo.delete_item(
                TableName=table,
                Key={'ImageKey': {'S': key}}
            )
            count += 1
            print(f"Deleted old tags for: {key}")
            
    print(f"\\nDone! Cleared {count} items.")

if __name__ == '__main__':
    main()
