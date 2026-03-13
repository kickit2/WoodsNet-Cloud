import boto3

dynamodb = boto3.client('dynamodb', region_name='us-east-1')
table_name = 'WoodsNetImageTags'

def wipe_table():
    print(f"Scanning {table_name}...")
    response = dynamodb.scan(TableName=table_name)
    items = response.get('Items', [])
    
    if not items:
        print("Table is already empty.")
        return
        
    print(f"Found {len(items)} items. Wiping...")
    
    for item in items:
        key = item['ImageKey']['S']
        dynamodb.delete_item(
            TableName=table_name,
            Key={'ImageKey': {'S': key}}
        )
        print(f"  Deleted: {key}")
        
    print("Wipe complete.")

if __name__ == '__main__':
    wipe_table()
