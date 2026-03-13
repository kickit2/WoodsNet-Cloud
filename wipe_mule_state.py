import boto3

dynamodb = boto3.client('dynamodb', region_name='us-east-1')
table_name = 'WoodsNetImageTags'

def wipe_table():
    response = dynamodb.scan(TableName=table_name)
    for item in response.get('Items', []):
        key = item['ImageKey']['S']
        if key.startswith('MULE_STATE'):
            dynamodb.delete_item(
                TableName=table_name,
                Key={'ImageKey': {'S': key}}
            )
            print(f"  Deleted: {key}")

if __name__ == '__main__':
    wipe_table()
