import json
import boto3
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

rekognition = boto3.client('rekognition')
dynamodb = boto3.client('dynamodb')
s3_client = boto3.client('s3')
sns_client = boto3.client('sns')

def fetch_weather_data(lat, lng):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,wind_speed_10m,surface_pressure&daily=moon_phase,moon_illumination&timezone=auto"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'WoodsNet/1.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            current = data.get('current', {})
            daily = data.get('daily', {})
            
            return {
                'temperature_c': current.get('temperature_2m'),
                'wind_kph': current.get('wind_speed_10m'),
                'pressure_hpa': current.get('surface_pressure'),
                'moon_phase': daily.get('moon_phase', [0])[0] if daily.get('moon_phase') else 0
            }
    except Exception as e:
        print(f"Failed to fetch weather: {e}")
        return None

def lambda_handler(event, context):
    """
    Triggered by S3 ObjectCreated events.
    Passes the new image to AWS Rekognition for label detection.
    Writes the resulting tags and object counts to DynamoDB.
    """
    
    # Target DynamoDB table name
    table_name = os.environ.get('DYNAMODB_TABLE_NAME', 'WoodsNetImageTags')
    
    try:
        # The S3 event payload can contain multiple records
        for record in event.get('Records', []):
            bucket = record['s3']['bucket']['name']
            # S3 keys in the event are URL encoded
            key = urllib.parse.unquote_plus(record['s3']['object']['key'])
            
            # We only care about .avif images in the mules directory.
            # Avoid processing the _config mappings file or UI assets if any.
            if not key.startswith('woods-net/mules/') or not key.lower().endswith('.avif'):
                print(f"Skipping analysis for non-capture file: {key}")
                continue
                
            parts = key.split('/')
            mule_id = parts[2] if len(parts) >= 3 else None
            
            weather_data = None
            if mule_id:
                try:
                    mapping_obj = s3_client.get_object(Bucket=bucket, Key='_config/mule_mappings.json')
                    mule_mappings = json.loads(mapping_obj['Body'].read().decode('utf-8'))
                    mule_info = mule_mappings.get(mule_id)
                    if isinstance(mule_info, dict) and 'lat' in mule_info and 'lng' in mule_info:
                        weather_data = fetch_weather_data(mule_info['lat'], mule_info['lng'])
                        print(f"Fetched weather data for {key}: {weather_data}")
                except Exception as e:
                    print(f"Could not load mule mappings or weather info: {e}")
                
            print(f"Analyzing Image: s3://{bucket}/{key}")
            
            # Call AWS Rekognition
            # We use a relatively high confidence threshold (75%) to avoid false positives (like a log looking like a bear).
            response = rekognition.detect_labels(
                Image={
                    'S3Object': {
                        'Bucket': bucket,
                        'Name': key
                    }
                },
                MaxLabels=15,
                MinConfidence=75
            )
            labels = response.get('Labels', [])
            
            # First pass: Check for antler/horn indicators anywhere in the scene
            has_antlers = any(l['Name'] in ['Antler', 'Horn'] for l in labels)
            has_animals = False
            has_person = False
            has_buck = False
            detected_tags = {}
            
            for label in labels:
                label_name = label['Name']
                
                # Rekognition groups specific animals under general categories.
                if label_name in ['Animal', 'Wildlife', 'Mammal', 'Bird', 'Antler', 'Horn']:
                    if label_name not in ['Antler', 'Horn']:
                        has_animals = True
                    continue # Skip recording generic tags or standalone antler parts
                
                if label_name in ['Person', 'Human', 'People']:
                    has_animals = True # Set flag so it's not filtered out as 'empty' by the 'Animals Only' UI filter
                    has_person = True
                
                # Custom logic for Deer sexing based on user request
                if label_name == 'Deer':
                    if has_antlers:
                        label_name = 'Antlered Buck'
                        has_buck = True
                    else:
                        label_name = 'Doe/Young'
                
                # If there are bounding boxes (Instances), we count them.
                # Otherwise, it's a general scene tag (e.g. "Outdoors", "Nature", "Forest").
                # We prioritize specific nouns over general scene descriptions.
                
                # Let's filter out super generic tags to keep the UI clean
                ignore_list = ['Nature', 'Outdoors', 'Land', 'Plant', 'Vegetation', 'Tree', 'Woodland', 'Forest', 'Grass', 'Ground']
                if label_name in ignore_list:
                    continue
                
                count = len(label['Instances'])
                if count > 0:
                    detected_tags[label_name] = count
                else:
                    # It's a high-confidence tag without bounding boxes (e.g., "Deer" but the AI isn't sure exactly how many or where)
                    detected_tags[label_name] = 1
                    
            # If no specific tags were found, but we flagged "Animal", ensure we at least record that.
            if has_animals and not detected_tags:
                detected_tags["Unknown Wildlife"] = 1
                
            # Second Pass: AWS Rekognition Custom Labels (Target Buck / Age Estimation)
            # This only runs if the user has trained a specific model and provided the ARN, AND a buck was detected.
            custom_model_arn = os.environ.get('CUSTOM_LABELS_PROJECT_ARN')
            if custom_model_arn and has_buck:
                try:
                    custom_response = rekognition.detect_custom_labels(
                        ProjectVersionArn=custom_model_arn,
                        Image={'S3Object': {'Bucket': bucket, 'Name': key}},
                        MinConfidence=60
                    )
                    for custom_label in custom_response.get('CustomLabels', []):
                        # Use an emoji prefix to visually separate AI-Trained tags from standard AWS tags on the UI
                        detected_tags[f"🎯 {custom_label['Name']}"] = 1
                except Exception as e:
                    print(f"Skipping custom labels analysis (model might be turned off): {e}")
                
            print(f"Detected Tags for {key}: {detected_tags}")
            
            # Convert dictionary into DynamoDB AttributeValue format
            # { 'Deer': {'N': '2'}, 'Raccoon': {'N': '1'} }
            dynamo_tags = {k: {'N': str(v)} for k, v in detected_tags.items()}
            
            # Store in DynamoDB
            item = {
                'ImageKey': {'S': key},
                'HasAnimals': {'BOOL': has_animals},
                'Tags': {'M': dynamo_tags}
            }
            
            if weather_data:
                t = weather_data.get('temperature_c')
                w = weather_data.get('wind_kph')
                p = weather_data.get('pressure_hpa')
                m = weather_data.get('moon_phase')
                
                # DynamoDB numbers must be passed as strings
                item['Weather'] = {
                    'M': {
                        'temp': {'N': str(t) if t is not None else '0'},
                        'wind': {'N': str(w) if w is not None else '0'},
                        'pressure': {'N': str(p) if p is not None else '0'},
                        'moon': {'N': str(m) if m is not None else '0'}
                    }
                }
                
            dynamodb.put_item(
                TableName=table_name,
                Item=item
            )
            
            # Update Mule Hardware State in DynamoDB for the Live Dashboard
            state_item = {
                'ImageKey': {'S': f"MULE_STATE#{mule_id}"},
                'LastHeartbeat': {'S': datetime.now(timezone.utc).isoformat()},
                # Mocking hardware telemetry for the MVP dashboard
                'Battery': {'N': '92'}, 
                'Signal': {'N': '-68'},
                'PowerLevel': {'S': 'PL3_ACTIVE'}
            }
            dynamodb.put_item(
                TableName=table_name,
                Item=state_item
            )
            
            print(f"Successfully saved tags and state to DynamoDB for {key}")
            
            # Trigger SNS Alerts for high-priority subjects
            sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
            if sns_topic_arn and (has_person or has_buck):
                subject = "🚨 trespasser Alert" if has_person else "🦌 Target Alert"
                msg_body = f"Woods-Net AI detected: {'PERSON' if has_person else 'ANTLERED BUCK'}\n"
                msg_body += f"Camera ID: {mule_id or 'Unknown'}\n"
                msg_body += f"File: {key}\n"
                
                try:
                    sns_client.publish(
                        TopicArn=sns_topic_arn,
                        Message=msg_body,
                        Subject=subject
                    )
                    print(f"SNS Alert Published for {key}")
                except Exception as e:
                    print(f"Failed to publish SNS alert: {e}")
            
    except Exception as e:
        print(f"Error processing S3 Event: {e}")
        # We don't necessarily want to fail the lambda and retry indefinitely if an image is corrupted.
        # But depending on the queue configuration, raising the exception might be desired.
        raise e
        
    return {
        'statusCode': 200,
        'body': json.dumps('Analysis Complete')
    }
